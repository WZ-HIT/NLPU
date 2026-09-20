"""Capture shared and per-task checkpoint layers.

A capture is write-once: re-running it over unchanged evidence is a no-op, and
changed evidence is refused unless the caller explicitly asks to replace the
active checkpoint, in which case the old one is moved into ``restore-backups``.
Nothing is ever deleted.
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..core import BatchError, canonical_sha256, sha256_file, write_json
from ..orchestrator import Ledger
from . import layout
from .layout import ExcludedDir

METHODS = ("openspec", "speckit", "cc-sdd")


def _ledger_events(bench: Path) -> dict[str, list[dict[str, Any]]]:
    """Every batch ledger, chain-validated. A broken chain aborts the capture."""
    schema = bench / "schemas/batch-ledger-event-v1.schema.json"
    events: dict[str, list[dict[str, Any]]] = {}
    runs = bench / layout.DEFAULT_BATCH_RUNS
    if not runs.is_dir():
        return events
    for directory in sorted(runs.iterdir()):
        ledger_path = directory / "ledger.jsonl"
        if not ledger_path.is_file():
            continue
        lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            continue
        batch_id = json.loads(lines[0])["batch_id"]
        events[batch_id] = Ledger(ledger_path, batch_id, schema).read()
    return events


def covered_targets(bench: Path, task_id: str) -> list[dict[str, Any]]:
    """Ledger targets for one task, newest state per target."""
    latest: dict[tuple, dict[str, Any]] = {}
    for batch_id, events in _ledger_events(bench).items():
        for event in events:
            target = event["target"]
            if target["task_id"] != task_id:
                continue
            key = (
                batch_id,
                target["method"],
                target["stage"],
                target["run_id"],
                target["update_mode"] or "",
            )
            latest[key] = {
                "batch_id": batch_id,
                "method": target["method"],
                "stage": target["stage"],
                "run_id": target["run_id"],
                "update_mode": target["update_mode"],
                "state": event["state"],
                "attempt": event["attempt"],
            }
    return [latest[key] for key in sorted(latest)]


def batch_run_summaries(bench: Path) -> list[dict[str, Any]]:
    summaries = []
    for batch_id, events in sorted(_ledger_events(bench).items()):
        path = bench / layout.DEFAULT_BATCH_RUNS / batch_id / "ledger.jsonl"
        summaries.append(
            {
                "batch_id": batch_id,
                "ledger_event_count": len(events),
                "ledger_sha256": sha256_file(path),
                "ledger_last_event_sha256": events[-1]["event_sha256"] if events else None,
            }
        )
    return summaries


# --------------------------------------------------------------------------
# Shared layer
# --------------------------------------------------------------------------


def _tree_entries(bench: Path, relative: str) -> list[tuple[str, Path]]:
    root = bench / relative
    if not root.exists():
        return []
    kept, _ = layout.walk_tree(
        root, skip_names=layout.SKIP_NAMES, skip_suffixes=layout.SKIP_SUFFIXES
    )
    return kept


def _docker_image_rows(bench: Path) -> list[dict[str, Any]]:
    images: dict[str, dict[str, Any]] = {}
    for lock_path in sorted((bench / layout.DEFAULT_IMAGES).glob("*/deployment-lock.json")):
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for role, record in sorted(lock.get("images", {}).items()):
            tag = record["tag"]
            row = images.setdefault(
                tag,
                {
                    "role": role,
                    "base_sha": lock["base_sha"],
                    "tag": tag,
                    "image_id": record["image_id"],
                    "present_locally": False,
                    "packaged": False,
                },
            )
            row["present_locally"] = _image_present(tag, record["image_id"])
    return [images[tag] for tag in sorted(images)]


def _image_present(tag: str, image_id: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0 and result.stdout.decode().strip() == image_id


def capture_shared(
    *, bench: Path, repository_root: Path, refresh: bool = False, with_images: bool = True
) -> dict[str, Any]:
    stamp = layout.utc_stamp()
    layer = layout.shared_dir(bench)

    payloads: list[dict[str, Any]] = []
    plan: list[tuple[str, str]] = [
        ("baselines.tar.gz", layout.DEFAULT_BASELINES),
        ("batch-images.tar.gz", layout.DEFAULT_IMAGES),
        ("batch-runs.tar.gz", layout.DEFAULT_BATCH_RUNS),
    ]
    contents: dict[str, Any] = {}
    collected: dict[str, list[tuple[str, Path]]] = {}
    for name, relative in plan:
        entries = _tree_entries(bench, relative)
        if not entries:
            continue
        _, manifest_sha = layout.manifest_lines(entries)
        collected[name] = entries
        contents[name] = {"install_path": relative, "file_manifest_sha256": manifest_sha}

    baselines = []
    for lock_path in sorted((bench / layout.DEFAULT_BASELINES).glob("*/baseline-lock.json")):
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        baselines.append(
            {
                "base_sha": lock["base_sha"],
                "tree_sha": lock["tree_sha"],
                "lock_sha256": sha256_file(lock_path),
                "checkout_file_count": lock["checkout_file_count"],
                "checkout_manifest_sha256": lock["checkout_manifest_sha256"],
                "source_repository_path": lock["source_repository"]["path"],
            }
        )

    raw_inputs, deployment_config = layout.tracked_input_rows(bench, repository_root)
    tracked = raw_inputs + deployment_config
    dirty = [item for item in tracked if not item["worktree_matches_head"]]

    images = _docker_image_rows(bench) if with_images else []
    image_name = "docker-images.tar" if images else ""

    content_sha = canonical_sha256(
        {
            "payloads": contents,
            "baselines": baselines,
            "tracked": [{"path": item["path"], "sha256": item["sha256"]} for item in tracked],
            "dirty": [item["path"] for item in dirty],
            "images": [{"tag": row["tag"], "image_id": row["image_id"]} for row in images],
            "batch_runs": batch_run_summaries(bench),
        }
    )

    existing = layout.checkpoint_path(layer)
    if existing.is_file() and not refresh:
        current = json.loads(existing.read_text(encoding="utf-8"))
        if current.get("content_sha256") == content_sha:
            return _summary("shared", "UNCHANGED", layer, current)
        raise BatchError(
            "CHECKPOINT_ALREADY_EXISTS",
            "Shared layer already holds a different checkpoint; pass --refresh to replace it",
            path=str(existing),
        )
    if existing.is_file():
        layout.move_aside(layer, layout.backup_paths(bench, stamp, "replaced", "shared"))

    layout.ensure_private_dir(layout.payload_dir(layer))
    for name, relative in plan:
        if name not in contents:
            continue
        written = layout.write_payload(
            layout.payload_path(layer, name),
            collected[name],
            arc_prefix=contents[name]["install_path"],
        )
        written["install_path"] = contents[name]["install_path"]
        payloads.append(written)
    if image_name:
        payloads.append(_save_docker_images(layer, image_name, [row["tag"] for row in images]))
        for row in images:
            row["packaged"] = True

    document = {
        "schema_version": 1,
        "checkpoint_type": "SHARED",
        "checkpoint_id": f"shared-{stamp}",
        "created_at_utc": layout.utc_now(),
        "contains_api_secret": False,
        "content_sha256": content_sha,
        "raw_inputs": raw_inputs,
        "deployment_config": deployment_config,
        "tracked_inputs_packaged": [],
        "baselines": baselines,
        "images": images,
        "batch_runs": batch_run_summaries(bench),
        "payloads": payloads,
    }
    layout.write_sums(layer, payloads)
    write_json(layout.checkpoint_path(layer), document, refuse_overwrite=True)
    layout.make_private(layout.checkpoint_path(layer), directory=False)
    return _summary("shared", "CAPTURED", layer, document)


def _save_docker_images(layer: Path, name: str, tags: list[str]) -> dict[str, Any]:
    destination = layout.payload_path(layer, name)
    result = subprocess.run(
        ["docker", "save", "--output", str(destination), *tags],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise BatchError(
            "DOCKER_SAVE_FAILED",
            "Cannot export the pinned images",
            tags=tags,
            stderr=result.stderr.decode(errors="replace")[-1500:],
        )
    layout.make_private(destination, directory=False)
    return {
        "name": name,
        "kind": "docker-save",
        "tags": tags,
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        "member_count": len(tags),
        "file_manifest_sha256": None,
    }


# --------------------------------------------------------------------------
# Per-task layer
# --------------------------------------------------------------------------


def _method_metadata(task: Path, method: str) -> dict[str, Any]:
    runs = task / "runs" / method
    detect = runs / "detect"
    update = runs / "update"

    detect_run_ids = sorted(
        entry.name for entry in (detect / "executions").iterdir()
    ) if (detect / "executions").is_dir() else []

    update_runs = []
    if (update / "executions").is_dir():
        for execution in sorted((update / "executions").iterdir()):
            for attempt in sorted(entry for entry in execution.iterdir() if entry.is_dir()):
                for mode_dir in sorted(attempt.glob("mode-*")):
                    update_runs.append(
                        {"run_id": execution.name, "mode": mode_dir.name[len("mode-") :]}
                    )

    sealed_manifest = update / "sealed-input" / "detection-manifest.json"
    sealed_planning = update / "sealed-input" / "planning-artifacts"
    initialization = task / "initialization" / method / "files"

    def tree_manifest_sha(root: Path) -> str | None:
        if not root.is_dir():
            return None
        kept, _ = layout.walk_tree(root, skip_names=layout.SKIP_NAMES)
        _, digest = layout.manifest_lines(kept)
        return digest

    return {
        "detect_run_ids": detect_run_ids,
        "update_runs": update_runs,
        "sealed_input_detection_manifest_sha256": sha256_file(sealed_manifest)
        if sealed_manifest.is_file()
        else None,
        "sealed_input_planning_manifest_sha256": tree_manifest_sha(sealed_planning),
        "detect_planning_manifest_sha256": tree_manifest_sha(detect / "planning-artifacts"),
        "initialization_manifest_sha256": tree_manifest_sha(initialization),
        "initialization_file_count": len(layout.walk_tree(initialization)[0])
        if initialization.is_dir()
        else 0,
    }


def capture_pr(
    *, bench: Path, repository_root: Path, task_id: str, refresh: bool = False
) -> dict[str, Any]:
    stamp = layout.utc_stamp()
    task = layout.task_root(bench, task_id)
    if not task.is_dir():
        raise BatchError("TASK_NOT_FOUND", "Task directory does not exist", path=str(task))
    public = json.loads((task / "task.json").read_text(encoding="utf-8"))
    base_sha = public["baseline"]["base_sha"]
    layer = layout.pr_dir(bench, task_id)

    entries, excluded = layout.walk_task_payload(task)
    by_method: dict[str, list[ExcludedDir]] = defaultdict(list)
    for item in excluded:
        by_method[item.relative.split("/")[1]].append(item)
    asserted: list[ExcludedDir] = []
    for method in sorted(by_method):
        asserted.extend(
            layout.assert_excluded_workspaces(
                task=task, method=method, base_sha=base_sha, excluded=by_method[method]
            )
        )

    gold = bench / layout.GOLD_DIRNAME / task_id
    gold_store = gold / "gold-store.json"
    gold_entries = layout.walk_tree(gold)[0] if gold.is_dir() else []

    methods = {method: _method_metadata(task, method) for method in METHODS}
    targets = covered_targets(bench, task_id)

    contents: dict[str, Any] = {}
    _, task_manifest_sha = layout.manifest_lines(entries)
    contents["task.tar.gz"] = {
        "install_path": f"{layout.TASKS_DIRNAME}/{task_id}",
        "file_manifest_sha256": task_manifest_sha,
    }
    if gold_entries:
        _, gold_manifest_sha = layout.manifest_lines(gold_entries)
        contents["gold.tar.gz"] = {
            "install_path": f"{layout.GOLD_DIRNAME}/{task_id}",
            "file_manifest_sha256": gold_manifest_sha,
        }

    content_sha = canonical_sha256(
        {
            "task_id": task_id,
            "base_sha": base_sha,
            "payloads": contents,
            "excluded": [item.as_dict() for item in asserted],
            "methods": methods,
            "targets": targets,
        }
    )

    existing = layout.checkpoint_path(layer)
    if existing.is_file() and not refresh:
        current = json.loads(existing.read_text(encoding="utf-8"))
        if current.get("content_sha256") == content_sha:
            return _summary("pr", "UNCHANGED", layer, current)
        raise BatchError(
            "CHECKPOINT_ALREADY_EXISTS",
            "This task already holds a different checkpoint; pass --refresh to replace it",
            path=str(existing),
        )
    if existing.is_file():
        layout.move_aside(layer, layout.backup_paths(bench, stamp, "replaced", task_id))

    layout.ensure_private_dir(layout.payload_dir(layer))
    payloads = []
    for name, members in (("task.tar.gz", entries), ("gold.tar.gz", gold_entries)):
        if name not in contents:
            continue
        written = layout.write_payload(
            layout.payload_path(layer, name), members, arc_prefix=contents[name]["install_path"]
        )
        written["install_path"] = contents[name]["install_path"]
        payloads.append(written)

    document = {
        "schema_version": 1,
        "checkpoint_type": "PR",
        "checkpoint_id": f"pr-{task_id}-{stamp}",
        "created_at_utc": layout.utc_now(),
        "contains_api_secret": False,
        "content_sha256": content_sha,
        "task_id": task_id,
        "pr_id": public["pr_id"],
        "base_sha": base_sha,
        "methods": methods,
        "gold_store_sha256": sha256_file(gold_store) if gold_store.is_file() else None,
        "excluded_regenerable": [item.as_dict() for item in asserted],
        "covered_targets": targets,
        "payloads": payloads,
    }
    layout.write_sums(layer, payloads)
    write_json(layout.checkpoint_path(layer), document, refuse_overwrite=True)
    layout.make_private(layout.checkpoint_path(layer), directory=False)
    return _summary("pr", "CAPTURED", layer, document)


def capture_pr_all(
    *, bench: Path, repository_root: Path, refresh: bool = False
) -> list[dict[str, Any]]:
    return [
        capture_pr(bench=bench, repository_root=repository_root, task_id=task_id, refresh=refresh)
        for task_id in layout.task_ids(bench)
    ]


def _summary(kind: str, status: str, layer: Path, document: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": status,
        "path": str(layer),
        "checkpoint_id": document.get("checkpoint_id"),
        "content_sha256": document.get("content_sha256"),
        "payload_count": len(document.get("payloads", [])),
        "payload_bytes": layout.payload_sizes(document.get("payloads", [])),
    }


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


def status(bench: Path) -> dict[str, Any]:
    layers = []
    for kind, directory in (("shared", layout.shared_dir(bench)),):
        document = _read_document(directory)
        layers.append(
            {
                "kind": kind,
                "name": kind,
                "path": str(directory),
                "captured": document is not None,
                "checkpoint_id": (document or {}).get("checkpoint_id"),
                "payload_bytes": layout.payload_sizes((document or {}).get("payloads", [])),
                "baseline_count": len((document or {}).get("baselines", [])),
                "image_count": len((document or {}).get("images", [])),
            }
        )
    for task_id in layout.task_ids(bench):
        directory = layout.pr_dir(bench, task_id)
        document = _read_document(directory)
        layers.append(
            {
                "kind": "pr",
                "name": task_id,
                "path": str(directory),
                "captured": document is not None,
                "checkpoint_id": (document or {}).get("checkpoint_id"),
                "payload_bytes": layout.payload_sizes((document or {}).get("payloads", [])),
                "covered_target_count": len((document or {}).get("covered_targets", [])),
            }
        )
    return {
        "schema_version": 1,
        "layers": layers,
        "total_payload_bytes": sum(item["payload_bytes"] for item in layers),
        "run_lock_holders": layout.run_lock_holders(bench),
        "api_key_present": layout.api_key_path().is_file(),
    }


def _read_document(layer: Path) -> dict[str, Any] | None:
    path = layout.checkpoint_path(layer)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
