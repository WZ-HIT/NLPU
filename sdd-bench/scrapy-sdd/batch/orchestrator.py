"""Approved-plan Detect/Update batch orchestrator with an append-only ledger."""

from __future__ import annotations

import contextlib
import fcntl
import functools
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from .core import BatchError, canonical_sha256, sha256_file, write_json
from .prepare_run import load_prepared
from .stages import (
    detect_targets,
    update_tests,
    validate_detection_prerequisite,
    validate_update_policy,
)

TERMINAL = {"DETECT_SEALED", "UPDATE_SEALED", "EVALUATED"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise BatchError("ABSOLUTE_CONFIG_PATH", "Batch config paths must be repository-relative", path=value)
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise BatchError("CONFIG_PATH_ESCAPE", "Batch config path escapes repository", path=value) from exc
    return resolved


def _schema_validate(value: dict[str, Any], schema: Path, code: str) -> None:
    errors = sorted(
        Draft202012Validator(
            json.loads(schema.read_text(encoding="utf-8")), format_checker=FormatChecker()
        ).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise BatchError(code, "JSON document failed schema", errors=[error.message for error in errors])


def _artifact(root: Path, value: dict[str, str], label: str) -> Path:
    path = _resolve(root, value["path"])
    if path.is_symlink() or not path.is_file() or sha256_file(path) != value["sha256"]:
        raise BatchError("BATCH_ARTIFACT_MISMATCH", f"{label} is missing or changed", path=value["path"])
    return path


def validate_batch_config(
    config_path: Path, bench: Path, repository_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if config_path.is_symlink() or not config_path.is_file():
        raise BatchError("INVALID_BATCH_CONFIG", "Batch config must be a regular non-symlink file")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _schema_validate(config, bench / "schemas/batch-run-v1.schema.json", "BATCH_SCHEMA_INVALID")
    approved = config["approved_plan"]
    plan_path = _artifact(repository_root, {"path": approved["path"], "sha256": approved["sha256"]}, "plan")
    report_path = _artifact(
        repository_root,
        {"path": approved["provision_report_path"], "sha256": approved["provision_report_sha256"]},
        "provision report",
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != approved["plan_id"]:
        raise BatchError("BATCH_PLAN_ID_MISMATCH", "Batch plan ID does not match plan file")
    approval = report.get("plan", {})
    if (
        report.get("status") not in {"READY", "TOPOLOGY_WARNING"}
        or approval.get("explicitly_approved_plan_id") != approved["plan_id"]
        or approval.get("sha256") != approved["sha256"]
    ):
        raise BatchError("PLAN_NOT_APPROVED", "Provision report does not prove explicit plan approval")
    planned = {item["task_id"]: item for item in plan["tasks"]}
    targets: list[dict[str, Any]] = []
    seen_tasks: set[str] = set()
    for task_entry in config["tasks"]:
        task_id = task_entry["task_id"]
        if task_id in seen_tasks:
            raise BatchError("DUPLICATE_TASK", "Task appears more than once", task_id=task_id)
        seen_tasks.add(task_id)
        if task_id not in planned:
            raise BatchError("TASK_NOT_IN_APPROVED_PLAN", "Task is outside approved plan", task_id=task_id)
        task_manifest = _artifact(repository_root, task_entry["task_manifest"], "task manifest")
        task = json.loads(task_manifest.read_text(encoding="utf-8"))
        if task.get("task_id") != task_id or task.get("baseline", {}).get("base_sha") != planned[task_id]["baseline"]["base_sha"]:
            raise BatchError("TASK_PLAN_MISMATCH", "Task manifest differs from approved plan", task_id=task_id)
        seen_methods: set[str] = set()
        for method_entry in task_entry["methods"]:
            method = method_entry["method"]
            if method in seen_methods:
                raise BatchError("DUPLICATE_METHOD", "Method appears more than once", task_id=task_id, method=method)
            seen_methods.add(method)
            detect_run = method_entry["detect"]["run_id"]
            targets.append({
                "task_id": task_id, "task_manifest": task_manifest, "method": method,
                "stage": "detect", "run_id": detect_run, "mode": None, "policy": None,
                "policy_sha256": None,
            })
            seen_runs: set[str] = set()
            for update in method_entry["updates"]:
                if update["run_id"] in seen_runs:
                    raise BatchError("DUPLICATE_UPDATE_RUN_ID", "Update run ID must be unique per task/method")
                seen_runs.add(update["run_id"])
                policy_path = _artifact(repository_root, update["policy"], "Update policy")
                policy, _, _, _ = validate_update_policy(
                    task_manifest=task_manifest, policy_path=policy_path, bench=bench,
                    method=method, run_id=update["run_id"],
                    expected_file_sha256=update["policy"]["sha256"],
                )
                if policy["mode"] != update["mode"]:
                    raise BatchError("BATCH_POLICY_MODE_MISMATCH", "Batch mode differs from immutable policy")
                targets.append({
                    "task_id": task_id, "task_manifest": task_manifest, "method": method,
                    "stage": "update", "run_id": update["run_id"], "mode": update["mode"],
                    "policy": policy_path, "policy_sha256": update["policy"]["sha256"],
                })
    return config, targets


def validate_prepared_manifest(
    manifest_path: Path, bench: Path, repository_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load P1's frozen contract and adapt it to unchanged stage runners."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if raw.get("manifest_type") == "PREPARED_ROUND":
        from .rounds import load_round
        manifest = load_round(manifest_path, root=repository_root)
    else:
        manifest = load_prepared(manifest_path, root=repository_root)
    targets = []
    seen = set()
    for item in manifest["targets"]:
        identity = (item["task_id"], item["method"], item["stage"], item["mode"], item["run_id"])
        if identity in seen:
            raise BatchError("PREPARED_TARGET_DUPLICATE", "Prepared target identity is duplicated")
        seen.add(identity)
        task_manifest = _artifact(repository_root, item["task_manifest"], "task manifest")
        policy = None
        policy_sha256 = None
        if item["policy"] is not None:
            policy = _artifact(repository_root, item["policy"], "Update policy")
            policy_sha256 = item["policy"]["sha256"]
        targets.append({
            "target_id": item["target_id"], "task_id": item["task_id"],
            "task_manifest": task_manifest, "method": item["method"],
            "stage": item["stage"], "run_id": item["run_id"],
            "mode": item["mode"], "policy": policy,
            "policy_sha256": policy_sha256,
        })
    return {
        "batch_id": manifest["prepared_id"],
        "prepared_id": manifest["prepared_id"],
        "experiment_id": manifest["experiment_id"],
        "manifest_path": str(manifest_path),
        "approved_plan": manifest["inputs"].get("approved_plan"),
        "approved_plans": [json.loads(_artifact(repository_root, ref, "source batch").read_text(encoding="utf-8"))["approved_plan"] for ref in manifest["inputs"]["sources"]] if manifest.get("manifest_type") == "PREPARED_ROUND" else None,
        "evaluation": manifest["inputs"]["evaluation"],
        "source_batch": manifest["inputs"].get("source_batch"),
    }, targets


def target_key(target: dict[str, Any]) -> str:
    return ":".join([
        target["task_id"], target["method"], target["stage"], target["run_id"],
        target["mode"] or "none",
    ])


def _ensure_detect_barrier(
    *, config: dict[str, Any], all_targets: list[dict[str, Any]], latest: dict[str, dict[str, Any]],
    run_root: Path, bench: Path, repository_root: Path,
) -> dict[str, Any]:
    detect_targets_all = [item for item in all_targets if item["stage"] == "detect"]
    records = []
    blockers = []
    for target in detect_targets_all:
        key = target_key(target)
        event = latest.get(key)
        if event is None or event["state"] != "DETECT_SEALED":
            blockers.append(key)
            continue
        task = json.loads(target["task_manifest"].read_text(encoding="utf-8"))
        manifest, path, file_sha = validate_detection_prerequisite(
            task=task, task_root=target["task_manifest"].parent,
            method=target["method"], bench=bench,
        )
        records.append({
            "task_id": target["task_id"], "method": target["method"],
            "run_id": target["run_id"], "base_sha": task["baseline"]["base_sha"],
            "detection_manifest": {
                "path": str(path.relative_to(repository_root)), "sha256": file_sha,
                "seal_sha256": manifest["seal"]["payload_sha256"],
            },
        })
    if blockers:
        raise BatchError(
            "DETECT_BARRIER_INCOMPLETE", "All task/method Detect runs must seal before Update",
            blockers=sorted(blockers),
        )
    records.sort(key=lambda item: (item["task_id"], item["method"]))
    barrier = {
        "schema_version": 1, "barrier_type": "GLOBAL_DETECT_BARRIER",
        "batch_id": config["batch_id"], "status": "SEALED",
        "detect_count": len(records), "expected_detect_count": len(detect_targets_all),
        "records": records,
    }
    barrier["barrier_sha256"] = canonical_sha256(barrier)
    path = run_root / "detect-barrier.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != barrier:
            raise BatchError("DETECT_BARRIER_MISMATCH", "Existing Detect barrier differs from current seals")
    else:
        write_json(path, barrier, refuse_overwrite=True)
    return barrier


class Ledger:
    def __init__(self, path: Path, batch_id: str, schema: Path) -> None:
        self.path = path
        self.batch_id = batch_id
        self.schema = schema
        self.lock_path = path.with_suffix(".lock")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        previous = None
        for index, event in enumerate(events, 1):
            _schema_validate(event, self.schema, "LEDGER_SCHEMA_INVALID")
            payload = dict(event)
            supplied = payload.pop("event_sha256")
            if (
                event["batch_id"] != self.batch_id
                or event["sequence"] != index
                or event["previous_event_sha256"] != previous
                or canonical_sha256(payload) != supplied
            ):
                raise BatchError("LEDGER_CHAIN_INVALID", "Append-only ledger hash chain is invalid")
            previous = supplied
        return events

    def append(self, action: str, target: dict[str, Any], state: str, attempt: int, details: Any) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            events = self.read()
            event = {
                "schema_version": 1, "batch_id": self.batch_id, "sequence": len(events) + 1,
                "recorded_at_utc": _now(), "action": action,
                "target": {
                    "task_id": target["task_id"], "method": target["method"],
                    "stage": target["stage"], "run_id": target["run_id"],
                    "update_mode": target["mode"],
                },
                "state": state, "attempt": attempt,
                "previous_event_sha256": events[-1]["event_sha256"] if events else None,
                "details_sha256": canonical_sha256(details),
            }
            event["event_sha256"] = canonical_sha256(event)
            _schema_validate(event, self.schema, "LEDGER_SCHEMA_INVALID")
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return event


def _filter_targets(
    targets: Iterable[dict[str, Any]], *, task_ids: set[str], methods: set[str],
    modes: set[str], stages: set[str],
) -> list[dict[str, Any]]:
    return [
        item for item in targets
        if item["stage"] in stages
        and (not task_ids or item["task_id"] in task_ids)
        and (not methods or item["method"] in methods)
        and (item["stage"] != "update" or not modes or item["mode"] in modes)
    ]


def _latest(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for event in events:
        # A resume skip records an idempotent observation; it must not replace
        # the terminal state it observed or a later --resume would run again.
        if event["state"] == "SKIPPED_RESUME" or event["action"] in {"dry-run", "probe"}:
            continue
        key = ":".join([
            event["target"]["task_id"], event["target"]["method"], event["target"]["stage"],
            event["target"]["run_id"], event["target"]["update_mode"] or "none",
        ])
        result[key] = event
    return result


MUTATING_COMMANDS = {"detect", "update", "all", "probe"}


@contextlib.contextmanager
def _run_duration_lock(run_root: Path, batch_id: str):
    """Hold ``batch/runs/<batch_id>/run.lock`` for one whole orchestration.

    ``Ledger.lock`` only spans a single append, so it cannot tell an outside
    observer that a run is in flight. This lock can: it is taken with LOCK_NB so
    a second concurrent run of the same batch_id fails fast instead of racing on
    a ``_latest`` snapshot read outside the ledger lock.
    """
    run_root.mkdir(parents=True, exist_ok=True)
    path = run_root / "run.lock"
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BatchError(
                "BATCH_RUN_ACTIVE",
                "Another run holds this batch_id; refusing to orchestrate concurrently",
                batch_id=batch_id,
                lock=str(path),
            ) from None
        try:
            yield path
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _batch_id_of(config_path: Path) -> str:
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
        value = document.get("prepared_id", document.get("batch_id"))
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return ""
    return value if isinstance(value, str) else ""


def orchestrate(
    *, command: str, config_path: Path | None = None, manifest_path: Path | None = None,
    bench: Path, repository_root: Path,
    dry_run: bool, resume: bool, retries: set[str], task_ids: set[str],
    methods: set[str], modes: set[str], recover_detects: set[str] | None = None,
    archive: bool = True,
) -> dict[str, Any]:
    """Public entry point: read-only commands run bare, the rest hold a run lock."""
    run = functools.partial(
        _orchestrate, command=command, config_path=config_path, manifest_path=manifest_path, bench=bench,
        repository_root=repository_root, dry_run=dry_run, resume=resume,
        retries=retries, task_ids=task_ids, methods=methods, modes=modes,
        recover_detects=recover_detects, archive=archive,
    )
    source_path = manifest_path or config_path
    if source_path is None:
        raise BatchError("RUN_SOURCE_REQUIRED", "A prepared manifest or legacy config is required")
    batch_id = _batch_id_of(source_path) if command in MUTATING_COMMANDS else ""
    if not batch_id:
        return run()
    with _run_duration_lock(bench / "batch/runs" / batch_id, batch_id):
        return run()


def _orchestrate(
    *, command: str, config_path: Path | None, manifest_path: Path | None,
    bench: Path, repository_root: Path,
    dry_run: bool, resume: bool, retries: set[str], task_ids: set[str],
    methods: set[str], modes: set[str], recover_detects: set[str] | None = None,
    archive: bool = True,
) -> dict[str, Any]:
    recover_detects = recover_detects or set()
    if manifest_path is not None:
        config, all_targets = validate_prepared_manifest(manifest_path, bench, repository_root)
    elif config_path is not None:
        config, all_targets = validate_batch_config(config_path, bench, repository_root)
    else:
        raise BatchError("RUN_SOURCE_REQUIRED", "A prepared manifest or legacy config is required")
    if manifest_path is not None and command in MUTATING_COMMANDS:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if raw.get("manifest_type") == "PREPARED_ROUND" and (bench / "Log/reports/round-archives" / config["batch_id"]).exists():
            raise BatchError("ROUND_ARCHIVED", "Archived round is immutable; choose a new round label")
    probe = command == "probe" or dry_run
    stages = {"detect"} if command == "detect" else {"update"} if command == "update" else {"detect", "update"}
    selected = _filter_targets(
        all_targets, task_ids=task_ids, methods=methods, modes=modes, stages=stages
    )
    selected.sort(key=lambda item: (0 if item["stage"] == "detect" else 1, item["task_id"], item["method"], item["run_id"]))
    if command in {"update", "all"} and "update" in stages and not any(x["stage"] == "update" for x in selected):
        raise BatchError("NO_EXPLICIT_UPDATE_POLICIES", "No explicitly selected Update policy matches this run")
    if command in {"detect", "update", "all", "probe"} and not selected:
        raise BatchError("NO_MATCHING_TARGETS", "No batch targets match the explicit filters")
    selected_keys = {target_key(item) for item in selected}
    unknown_retries = retries - selected_keys
    if command in {"detect", "update", "all", "probe"} and unknown_retries:
        raise BatchError(
            "UNKNOWN_RETRY_TARGET", "Retry target is not part of this filtered run",
            targets=sorted(unknown_retries),
        )
    unknown_recoveries = recover_detects - selected_keys
    if unknown_recoveries:
        raise BatchError(
            "UNKNOWN_DETECT_RECOVERY_TARGET", "Recovery target is not part of this filtered run",
            targets=sorted(unknown_recoveries),
        )
    run_root = bench / "batch/runs" / config["batch_id"]
    ledger = Ledger(
        run_root / "ledger.jsonl", config["batch_id"],
        bench / "schemas/batch-ledger-event-v1.schema.json",
    )
    events = ledger.read()
    latest = _latest(events)
    if command in {"status", "inspect"}:
        visible_keys = {target_key(item) for item in selected}
        return {
            "schema_version": 1, "batch_id": config["batch_id"],
            "prepared_id": config.get("prepared_id"), "command": "inspect", "status": "OK",
            "ledger_valid": True, "event_count": len(events),
            "targets": [{"key": key, "state": value["state"], "attempt": value["attempt"],
                         "update_mode": value["target"]["update_mode"]}
                        for key, value in sorted(latest.items()) if key in visible_keys],
        }
    if command == "evaluate":
        updates = _filter_targets(
            all_targets, task_ids=task_ids, methods=methods, modes=modes, stages={"update"}
        )
        readiness = []
        for target in updates:
            event = latest.get(target_key(target))
            ready = event is not None and event["state"] == "UPDATE_SEALED"
            readiness.append({"target": target_key(target), "update_mode": target["mode"], "ready": ready})
        status = "READY" if readiness and all(x["ready"] for x in readiness) else "BLOCKED"
        report = {
            "schema_version": 1, "batch_id": config["batch_id"], "status": status,
            "evaluation_dispatched": False,
            "reason": "host_evaluator_not_dispatched_by_orchestrator" if status == "READY" else "updates_not_sealed",
            "targets": readiness,
        }
        path = run_root / "evaluation-dispatch.json"
        if not path.exists():
            write_json(path, report, refuse_overwrite=True)
        return report
    results = []
    barrier_checked = False
    for target in selected:
        if not probe and target["stage"] == "update" and not barrier_checked:
            _ensure_detect_barrier(
                config=config, all_targets=all_targets, latest=latest, run_root=run_root,
                bench=bench, repository_root=repository_root,
            )
            barrier_checked = True
        key = target_key(target)
        previous = latest.get(key)
        # Dry-run evidence is append-only, but it is not a started formal
        # execution and therefore cannot force --resume/--retry for that run.
        formal_previous = previous
        if probe or (previous and previous["action"] in {"dry-run", "probe"}):
            formal_previous = None
        retry = key in retries
        recover = key in recover_detects
        if recover and retry:
            raise BatchError("CONFLICTING_RETRY_RECOVERY", "A target cannot be retried and recovered together", target=key)
        if recover and (
            target["stage"] != "detect" or formal_previous is None
            or formal_previous["state"] != "FAILED"
        ):
            raise BatchError(
                "INVALID_DETECT_RECOVERY", "Recovery requires a failed Detect attempt", target=key
            )
        if retry and (formal_previous is None or formal_previous["state"] not in {"BLOCKED", "FAILED"}):
            raise BatchError("INVALID_EXPLICIT_RETRY", "Retry target has no failed/blocked prior attempt", target=key)
        if formal_previous and formal_previous["state"] in TERMINAL:
            if not resume:
                raise BatchError("RUN_ALREADY_COMPLETE", "Use --resume to skip completed target", target=key)
            ledger.append(target["stage"], target, "SKIPPED_RESUME", formal_previous["attempt"], {"previous": formal_previous["event_sha256"]})
            results.append({"target": key, "target_id": target.get("target_id"), "state": "SKIPPED_RESUME", "update_mode": target["mode"], "attempt": formal_previous["attempt"]})
            continue
        if formal_previous and not retry and not resume:
            raise BatchError("RUN_ALREADY_STARTED", "Use --resume or an explicit --retry target", target=key)
        attempt = (formal_previous["attempt"] + 1) if retry else (formal_previous["attempt"] if formal_previous else 1)
        if probe:
            try:
                if target["stage"] == "detect":
                    result = detect_targets(
                        task_manifest=target["task_manifest"], method=target["method"],
                        run_id=target["run_id"], output=Path("/unused"), bench=bench,
                        repository_root=repository_root, dry_run=True,
                    )
                else:
                    result = update_tests(
                        task_manifest=target["task_manifest"], policy_path=target["policy"],
                        output=Path("/unused"), bench=bench, repository_root=repository_root,
                        dry_run=True, expected_policy_sha256=target["policy_sha256"],
                    )
                state = "DRY_RUN_READY"
            except BatchError as exc:
                result = {"error": exc.as_dict(), "update_mode": target["mode"]}
                state = "BLOCKED"
            ledger.append("probe", target, state, attempt, result)
            results.append({"target": key, "target_id": target.get("target_id"), "state": state, "update_mode": target["mode"], "result": result})
            continue
        if target["stage"] == "detect":
            if not recover:
                for state in ("PLANNED", "PREFLIGHT_READY", "DETECT_RUNNING"):
                    ledger.append("detect", target, state, attempt, {"target": key})
            output = (
                target["task_manifest"].parent / "runs" / target["method"] / "detect" /
                "executions" / target["run_id"] / f"attempt-{attempt}"
            )
            try:
                result = detect_targets(
                    task_manifest=target["task_manifest"], method=target["method"],
                    run_id=target["run_id"], output=output, bench=bench,
                    repository_root=repository_root, dry_run=False, recover_existing=recover,
                )
                state = "DETECT_SEALED"
            except Exception as exc:
                state = "FAILED"
                result = {"error": exc.as_dict() if isinstance(exc, BatchError) else {"message": str(exc)}}
        else:
            for state in ("UPDATE_POLICY_SELECTED", "UPDATE_READY", "UPDATE_RUNNING"):
                ledger.append("update", target, state, attempt, {"target": key, "mode": target["mode"]})
            output = (
                target["task_manifest"].parent / "runs" / target["method"] / "update" /
                "executions" / target["run_id"] / f"attempt-{attempt}"
            )
            try:
                result = update_tests(
                    task_manifest=target["task_manifest"], policy_path=target["policy"],
                    output=output, bench=bench, repository_root=repository_root, dry_run=False,
                    expected_policy_sha256=target["policy_sha256"],
                )
                state = "UPDATE_SEALED" if result["status"] == "SEALED" else "BLOCKED"
            except Exception as exc:
                state = "FAILED"
                result = {"error": exc.as_dict() if isinstance(exc, BatchError) else {"message": str(exc)}}
        event = ledger.append(target["stage"], target, state, attempt, result)
        latest[key] = event
        results.append({"target": key, "target_id": target.get("target_id"), "state": state,
                        "update_mode": target["mode"], "attempt": attempt,
                        "ledger_sequence": event["sequence"], "result": result})
    barrier = None
    if not probe and command in {"detect", "all"} and not any(
        item["state"] in {"BLOCKED", "FAILED"} for item in results if ":detect:" in item["target"]
    ):
        barrier = _ensure_detect_barrier(
            config=config, all_targets=all_targets, latest=latest, run_root=run_root,
            bench=bench, repository_root=repository_root,
        )
    summary = {
        "schema_version": 1, "batch_id": config["batch_id"], "command": command,
        "prepared_id": config.get("prepared_id"), "dry_run": probe,
        "resume": resume, "selected_count": len(selected),
        "status": "BLOCKED" if any(x["state"] in {"BLOCKED", "FAILED"} for x in results) else "READY",
        "results": results,
    }
    if barrier is not None:
        summary["detect_barrier_sha256"] = barrier["barrier_sha256"]
    if probe:
        run_root.mkdir(parents=True, exist_ok=True)
        dry_path = run_root / "probe-report.json"
        if dry_path.exists():
            suffix = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()[:12]
            dry_path = run_root / f"probe-report-{suffix}.json"
        write_json(dry_path, summary, refuse_overwrite=True)
        summary["report"] = str(dry_path.relative_to(repository_root))
        # A dry run reaches no conclusion, so it can never archive. Returning
        # here rather than guarding the call below keeps that a property of the
        # control flow instead of a boolean someone can invert.
        return summary
    if command in MUTATING_COMMANDS:
        summary["archive"] = _archive_after_run(
            bench=bench,
            repository_root=repository_root,
            config=config,
            config_path=config_path,
            enabled=archive and config_path is not None,
        )
    return summary


def _archive_after_run(
    *, bench: Path, repository_root: Path, config: dict[str, Any],
    config_path: Path, enabled: bool,
) -> dict[str, Any]:
    """Snapshot the run's results once the batch has concluded.

    This is an epilogue, never a step: an experiment that produced a result has
    succeeded at its job whether or not the archive could be written. Every
    exception is therefore caught and reported rather than raised, and the
    failure is recorded on disk so it survives the process that hit it. Only
    ``Exception`` is caught -- a ``KeyboardInterrupt`` must still interrupt.

    The import is deliberately inside the function. ``batch.archive`` loads the
    results viewer lazily, but keeping the import local means a future edit to
    that package cannot make ``batch.orchestrator`` unimportable, which would
    take down every command including read-only ones.
    """
    if not enabled:
        return {"schema_version": 1, "status": "DISABLED"}
    from .archive import archive_batch, record_failure

    batch_id = config["batch_id"]
    try:
        return archive_batch(
            bench=bench,
            repository_root=repository_root,
            batch_id=batch_id,
            config_path=config_path,
            reason="auto",
        )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        detail = (
            exc.as_dict()
            if isinstance(exc, BatchError)
            else {"code": type(exc).__name__, "message": str(exc)}
        )
        record_failure(bench, batch_id, detail)
        return {
            "schema_version": 1,
            "status": "ERROR",
            "batch_id": batch_id,
            "errors": [detail],
            "error_log": "Log/reports/archive/archive-errors.log",
        }
