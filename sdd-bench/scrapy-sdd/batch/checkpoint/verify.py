"""Read-only verification of captured checkpoint layers.

Verification re-derives every hash it can instead of trusting the metadata: the
payload archives are re-hashed, each payload is re-extracted into a scratch
directory and checked against its recorded file manifest, and the live baseline
caches, Docker images, and ledger are compared against what was recorded.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..core import BatchError, sha256_file
from . import layout
from .capture import batch_run_summaries, covered_targets

SCHEMA_DIR = "schemas"
SHARED_SCHEMA = "checkpoint-shared-v1.schema.json"
PR_SCHEMA = "checkpoint-pr-v1.schema.json"


def _record(checks: list[dict[str, Any]], name: str, status: str, **detail: Any) -> None:
    checks.append({"check": name, "status": status, **detail})


def _schema_validate(bench: Path, name: str, document: dict[str, Any]) -> None:
    from jsonschema import Draft202012Validator

    schema_path = bench / SCHEMA_DIR / name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        raise BatchError(
            "CHECKPOINT_SCHEMA_INVALID",
            "Checkpoint metadata failed schema validation",
            schema=str(schema_path),
            errors=[f"{'/'.join(str(p) for p in error.path)}: {error.message}" for error in errors[:20]],
        )


def _verify_payloads(layer: Path, document: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    expected = {relative: digest for digest, relative in layout.read_sums(layer)}
    recorded = {item["name"]: item for item in document["payloads"]}
    if set(expected) != {f"{layout.PAYLOAD_DIRNAME}/{name}" for name in recorded}:
        raise BatchError(
            "SUMS_MISMATCH",
            "SHA256SUMS does not cover exactly the recorded payloads",
            listed=sorted(expected),
            recorded=sorted(recorded),
        )
    for name, item in sorted(recorded.items()):
        path = layout.payload_path(layer, name)
        if not path.is_file():
            _record(checks, f"payload:{name}", "FAIL", reason="missing")
            continue
        actual = sha256_file(path)
        if actual != item["sha256"] or expected[f"{layout.PAYLOAD_DIRNAME}/{name}"] != actual:
            _record(
                checks,
                f"payload:{name}",
                "FAIL",
                reason="sha256 differs",
                recorded=item["sha256"],
                actual=actual,
            )
            continue
        if path.stat().st_size != item["size_bytes"]:
            _record(checks, f"payload:{name}", "FAIL", reason="size differs")
            continue
        if item.get("kind") == "docker-save":
            _record(checks, f"payload:{name}", "PASS", note="archive hash only")
            continue
        with tempfile.TemporaryDirectory(prefix="sdd-checkpoint-verify-") as temporary:
            layout.extract_payload(layer, name, Path(temporary))
            # Manifest paths are relative to install_path, which is also the
            # archive prefix, so the walk root is the install path under the
            # scratch directory rather than the scratch directory itself.
            root = Path(temporary) / item["install_path"]
            try:
                layout.check_manifest(root, layout.read_payload_manifest(layer, name))
            except BatchError as exc:
                _record(checks, f"payload:{name}", "FAIL", reason=exc.code, **exc.details)
                continue
        _record(checks, f"payload:{name}", "PASS", member_count=item["member_count"])


def _verify_tracked(repository_root: Path, rows: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    for row in rows:
        path = repository_root / row["path"]
        if not path.is_file():
            _record(checks, f"tracked:{row['path']}", "FAIL", reason="missing")
            continue
        actual = sha256_file(path)
        status = "PASS" if actual == row["sha256"] else "FAIL"
        _record(
            checks,
            f"tracked:{row['path']}",
            status,
            recorded=row["sha256"],
            actual=actual,
            worktree_matches_head=row["worktree_matches_head"],
        )


def _verify_baselines(bench: Path, rows: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    for row in rows:
        repo = bench / layout.DEFAULT_BASELINES / row["base_sha"] / "repository"
        if not repo.is_dir():
            _record(checks, f"baseline:{row['base_sha']}", "FAIL", reason="cache missing")
            continue
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        tree = result.stdout.decode().strip() if result.returncode == 0 else ""
        status = "PASS" if tree == row["tree_sha"] else "FAIL"
        detail: dict[str, Any] = {"recorded_tree": row["tree_sha"], "actual_tree": tree}
        present = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{row['base_sha']}^{{commit}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if present.returncode:
            status = "FAIL"
            detail["reason"] = "base commit object absent; provision could not reuse this cache"
        _record(checks, f"baseline:{row['base_sha']}", status, **detail)


def _verify_images(rows: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    for row in rows:
        probe = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", row["tag"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if probe.returncode:
            _record(
                checks,
                f"image:{row['tag']}",
                "SKIP",
                reason="image not loaded locally",
                present_when_captured=row["present_locally"],
            )
            continue
        actual = probe.stdout.decode().strip()
        status = "PASS" if actual == row["image_id"] else "FAIL"
        _record(
            checks, f"image:{row['tag']}", status, recorded=row["image_id"], actual=actual
        )


def verify_shared(*, bench: Path, repository_root: Path) -> dict[str, Any]:
    layer = layout.shared_dir(bench)
    document = json.loads(layout.checkpoint_path(layer).read_text(encoding="utf-8"))
    _schema_validate(bench, SHARED_SCHEMA, document)
    checks: list[dict[str, Any]] = []
    _verify_payloads(layer, document, checks)
    _verify_tracked(repository_root, document["raw_inputs"], checks)
    _verify_tracked(repository_root, document["deployment_config"], checks)
    _verify_baselines(bench, document["baselines"], checks)
    _verify_images(document["images"], checks)
    recorded_runs = {item["batch_id"]: item for item in document["batch_runs"]}
    for current in batch_run_summaries(bench):
        recorded = recorded_runs.get(current["batch_id"])
        if recorded is None:
            _record(checks, f"batch-runs:{current['batch_id']}", "FAIL", reason="not captured")
            continue
        status = "PASS" if recorded == current else "FAIL"
        _record(checks, f"batch-runs:{current['batch_id']}", status, recorded=recorded, actual=current)
    return _result("shared", layer, document, checks)


def verify_pr(*, bench: Path, repository_root: Path, task_id: str) -> dict[str, Any]:
    layer = layout.pr_dir(bench, task_id)
    document = json.loads(layout.checkpoint_path(layer).read_text(encoding="utf-8"))
    _schema_validate(bench, PR_SCHEMA, document)
    checks: list[dict[str, Any]] = []
    _verify_payloads(layer, document, checks)
    gold = bench / layout.GOLD_DIRNAME / task_id / "gold-store.json"
    if document["gold_store_sha256"] is None:
        _record(checks, "gold-store", "SKIP", reason="never audited")
    elif not gold.is_file():
        _record(checks, "gold-store", "FAIL", reason="missing")
    else:
        actual = sha256_file(gold)
        _record(
            checks,
            "gold-store",
            "PASS" if actual == document["gold_store_sha256"] else "FAIL",
            recorded=document["gold_store_sha256"],
            actual=actual,
        )
    _verify_methods(bench, task_id, document, checks)
    current = covered_targets(bench, task_id)
    if current != document["covered_targets"]:
        _record(
            checks,
            "covered-targets",
            "FAIL",
            reason="ledger state advanced past the checkpoint",
            recorded_count=len(document["covered_targets"]),
            actual_count=len(current),
        )
    else:
        _record(checks, "covered-targets", "PASS", count=len(current))
    return _result("pr", layer, document, checks)


def _verify_methods(
    bench: Path, task_id: str, document: dict[str, Any], checks: list[dict[str, Any]]
) -> None:
    """Re-derive the cross-artifact consistency reporting.py enforces at report time."""
    task = layout.task_root(bench, task_id)
    for method, recorded in sorted(document["methods"].items()):
        sealed = task / "runs" / method / "update" / "sealed-input" / "detection-manifest.json"
        executions = task / "runs" / method / "detect" / "executions"
        name = f"sealed-input:{method}"
        if recorded["sealed_input_detection_manifest_sha256"] is None:
            _record(checks, name, "SKIP", reason="Update never ran for this method")
            continue
        if not sealed.is_file():
            _record(checks, name, "FAIL", reason="sealed-input detection manifest missing")
            continue
        actual = sha256_file(sealed)
        if actual != recorded["sealed_input_detection_manifest_sha256"]:
            _record(
                checks,
                name,
                "FAIL",
                reason="sealed-input detection manifest changed",
                recorded=recorded["sealed_input_detection_manifest_sha256"],
                actual=actual,
            )
            continue
        mirrors = []
        if executions.is_dir():
            for run_dir in sorted(executions.iterdir()):
                for attempt in sorted(run_dir.glob("*/detection-manifest.json")):
                    if sha256_file(attempt) == actual:
                        mirrors.append(f"{run_dir.name}/{attempt.parent.name}")
        _record(
            checks,
            name,
            "PASS" if mirrors else "FAIL",
            reason=None if mirrors else "no detect execution mirrors the sealed manifest",
            mirroring_detect_runs=mirrors,
        )


def _result(kind: str, layer: Path, document: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [item for item in checks if item["status"] == "FAIL"]
    return {
        "schema_version": 1,
        "kind": kind,
        "path": str(layer),
        "checkpoint_id": document["checkpoint_id"],
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "failed_count": len(failed),
        "skipped_count": sum(1 for item in checks if item["status"] == "SKIP"),
    }
