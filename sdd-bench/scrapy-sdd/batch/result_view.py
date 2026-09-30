"""Canonical, gold-free result view indexed by the P2/P3 target key.

The view is derived from a frozen target source and the append-only ledger.  It
never changes a seal and deliberately contains no evaluation or gold fields.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .core import BatchError, canonical_sha256, sha256_file, write_json
from .orchestrator import Ledger, _latest, target_key, validate_batch_config, validate_prepared_manifest

VIEW_VERSION = 1
VIEW_TYPE = "TARGET_RESULT_VIEW"
TERMINAL_STATES = {"DETECT_SEALED", "UPDATE_SEALED", "EVALUATED"}


def target_id(target: dict[str, Any]) -> str:
    supplied = target.get("target_id")
    if isinstance(supplied, str):
        return supplied
    identity = {name: target[name] for name in ("task_id", "method", "stage", "mode", "run_id")}
    return "target-" + canonical_sha256(identity)[:24]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise BatchError("RESULT_VIEW_PATH_ESCAPE", "Result evidence escapes the repository", path=str(path)) from exc


def _load_source(source_path: Path, bench: Path, repository_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchError("RESULT_VIEW_SOURCE_INVALID", "Target source cannot be read", path=str(source_path)) from exc
    if not isinstance(raw, dict):
        raise BatchError("RESULT_VIEW_SOURCE_INVALID", "Target source must be a JSON object")
    if raw.get("manifest_type") == "PREPARED_EXPERIMENT":
        config, targets = validate_prepared_manifest(source_path, bench, repository_root)
        return config, targets, "prepared-manifest"
    if "approved_plan" in raw:
        config, targets = validate_batch_config(source_path, bench, repository_root)
        return config, targets, "batch-config"
    # Compatibility for pre-contract historical and test configs. The result
    # identity still comes from the same five fields and every task manifest is
    # hash checked; reporting and host evaluation continue to require the full
    # approved-plan validator before calling this builder.
    targets = []
    for task in raw.get("tasks", []):
        reference = task["task_manifest"]
        manifest = repository_root / reference["path"]
        if manifest.is_symlink() or not manifest.is_file() or sha256_file(manifest) != reference["sha256"]:
            raise BatchError("BATCH_ARTIFACT_MISMATCH", "task manifest is missing or changed")
        for method in task.get("methods", []):
            targets.append({"task_id": task["task_id"], "task_manifest": manifest, "method": method["method"],
                            "stage": "detect", "run_id": method["detect"]["run_id"], "mode": None,
                            "policy": None, "policy_sha256": None})
            for update in method.get("updates", []):
                targets.append({"task_id": task["task_id"], "task_manifest": manifest, "method": method["method"],
                                "stage": "update", "run_id": update["run_id"], "mode": update["mode"],
                                "policy": None, "policy_sha256": update.get("policy", {}).get("sha256")})
    return raw, targets, "batch-config"


def build(source_path: Path, bench: Path, repository_root: Path) -> dict[str, Any]:
    """Build and validate a deterministic view without writing anything."""
    repository_root = repository_root.resolve()
    bench = bench.resolve()
    source_path = source_path.resolve()
    config, targets, source_type = _load_source(source_path, bench, repository_root)
    keys = [target_key(item) for item in targets]
    if len(keys) != len(set(keys)):
        raise BatchError("RESULT_VIEW_DUPLICATE_TARGET", "Target keys are not unique")
    ids = [target_id(item) for item in targets]
    if len(ids) != len(set(ids)):
        raise BatchError("RESULT_VIEW_DUPLICATE_TARGET_ID", "Target ids are not unique")

    run_root = bench / "batch/runs" / config["batch_id"]
    ledger_path = run_root / "ledger.jsonl"
    ledger = Ledger(ledger_path, config["batch_id"], bench / "schemas/batch-ledger-event-v1.schema.json")
    events = ledger.read()
    latest = _latest(events)
    rows: dict[str, dict[str, Any]] = {}
    for target in targets:
        key = target_key(target)
        event = latest.get(key)
        state = event["state"] if event else "NOT_RECORDED"
        attempt = event["attempt"] if event else None
        execution = None
        seal = None
        if attempt is not None:
            execution_path = (
                target["task_manifest"].parent / "runs" / target["method"] / target["stage"]
                / "executions" / target["run_id"] / f"attempt-{attempt}"
            )
            if target["stage"] == "update":
                execution_path /= f'mode-{target["mode"]}'
            if execution_path.is_dir() and not execution_path.is_symlink():
                execution = _relative(execution_path, repository_root)
                seal_path = execution_path / "seal.json"
                if seal_path.is_file() and not seal_path.is_symlink():
                    seal = {"path": _relative(seal_path, repository_root), "sha256": sha256_file(seal_path)}
        task_document = json.loads(target["task_manifest"].read_text(encoding="utf-8"))
        rows[key] = {
            "target_key": key,
            "target_id": target_id(target),
            "task_id": target["task_id"],
            "pr_id": task_document.get("pr_id") if isinstance(task_document.get("pr_id"), int) else None,
            "title": task_document.get("title") if isinstance(task_document.get("title"), str) else "",
            "method": target["method"],
            "stage": target["stage"],
            "mode": target["mode"],
            "run_id": target["run_id"],
            "state": state,
            "attempt": attempt,
            "ledger_event": None if event is None else {
                "sequence": event["sequence"], "event_sha256": event["event_sha256"]
            },
            "execution_path": execution,
            "seal": seal,
        }
    states = Counter(row["state"] for row in rows.values())
    stages = Counter(row["stage"] for row in rows.values())
    view: dict[str, Any] = {
        "schema_version": VIEW_VERSION,
        "view_type": VIEW_TYPE,
        "batch_id": config["batch_id"],
        "prepared_id": config.get("prepared_id"),
        "experiment_id": config.get("experiment_id"),
        "source": {"type": source_type, "path": _relative(source_path, repository_root), "sha256": sha256_file(source_path)},
        "ledger": {
            "path": _relative(ledger_path, repository_root), "sha256": sha256_file(ledger_path),
            "event_count": len(events), "chain_tip_sha256": events[-1]["event_sha256"] if events else None,
        },
        "counts": {
            "target_count": len(rows), "detect_count": stages["detect"], "update_count": stages["update"],
            "terminal_count": sum(row["state"] in TERMINAL_STATES for row in rows.values()),
            "states": dict(sorted(states.items())),
        },
        "target_order": keys,
        "targets": rows,
    }
    view["view_sha256"] = canonical_sha256(view)
    validate(view, bench)
    return view


def validate(view: dict[str, Any], bench: Path) -> None:
    schema = json.loads((bench / "schemas/target-result-view-v1.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(view), key=lambda error: list(error.path))
    if errors:
        raise BatchError("RESULT_VIEW_SCHEMA_INVALID", errors[0].message, location=errors[0].json_path)
    payload = dict(view)
    supplied = payload.pop("view_sha256")
    if supplied != canonical_sha256(payload):
        raise BatchError("RESULT_VIEW_HASH_INVALID", "Result view self-hash differs")
    if view["target_order"] != list(view["targets"]):
        raise BatchError("RESULT_VIEW_ORDER_INVALID", "Target order and target index differ")
    if any(key != row["target_key"] for key, row in view["targets"].items()):
        raise BatchError("RESULT_VIEW_KEY_INVALID", "Target index key differs from its row")
    rows = list(view["targets"].values())
    expected_counts = {
        "target_count": len(rows),
        "detect_count": sum(row["stage"] == "detect" for row in rows),
        "update_count": sum(row["stage"] == "update" for row in rows),
        "terminal_count": sum(row["state"] in TERMINAL_STATES for row in rows),
        "states": dict(sorted(Counter(row["state"] for row in rows).items())),
    }
    if view["counts"] != expected_counts:
        raise BatchError("RESULT_VIEW_COUNTS_INVALID", "Result view counts differ from indexed targets")


def write(source_path: Path, bench: Path, repository_root: Path, output: Path | None = None) -> tuple[dict[str, Any], Path]:
    view = build(source_path, bench, repository_root)
    destination = output or bench / "batch/runs" / view["batch_id"] / "result-view.json"
    write_json(destination, view)
    return view, destination


def load(path: Path, bench: Path, repository_root: Path, *, verify_evidence: bool = True) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BatchError("RESULT_VIEW_MISSING", "Result view is missing", path=str(path))
    view = json.loads(path.read_text(encoding="utf-8"))
    validate(view, bench)
    if verify_evidence:
        for reference in (view["source"], view["ledger"]):
            evidence = repository_root / reference["path"]
            if evidence.is_symlink() or not evidence.is_file() or sha256_file(evidence) != reference["sha256"]:
                raise BatchError("RESULT_VIEW_EVIDENCE_CHANGED", "Result view evidence changed", path=reference["path"])
        for row in view["targets"].values():
            if row["seal"] is not None:
                seal = repository_root / row["seal"]["path"]
                if seal.is_symlink() or not seal.is_file() or sha256_file(seal) != row["seal"]["sha256"]:
                    raise BatchError("RESULT_VIEW_EVIDENCE_CHANGED", "Referenced seal changed", path=row["seal"]["path"])
        rebuilt = build(repository_root / view["source"]["path"], bench, repository_root)
        if view != rebuilt:
            raise BatchError("RESULT_VIEW_CONTENT_MISMATCH", "Result view differs from its source and ledger")
    return view
