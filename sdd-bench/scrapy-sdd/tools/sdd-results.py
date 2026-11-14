#!/usr/bin/env python3
"""Global SDD experiment result browser and self-contained HTML report builder."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse, parse_qs
import webbrowser

VERSION = "1.7.2"
VARIANTS = ("openspec", "speckit", "cc-sdd")
LABEL = {"openspec": "OpenSpec", "speckit": "Spec Kit", "cc-sdd": "cc-sdd"}
ARTIFACT_DIRS = ("outputs", "output-files", "artifacts", "generated-files")
TERMINAL_STATES = {"DETECT_SEALED", "UPDATE_SEALED", "EVALUATED"}
# task_id values become experiment ids, slugs and search text, so they are held to
# the same shape as batch_id. This is a discovery-time filter, never a path join.
SAFE_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
MAX_TEXT = 2 * 1024 * 1024
MAX_DIFF = 20 * 1024 * 1024
MAX_JSONL = 64 * 1024 * 1024


class ViewerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    root: Path
    audit_name: str
    modified: float
    source_kind: str = "legacy"
    config_path: Path | None = None
    batch_id: str | None = None
    task_id_filter: str | None = None


@dataclass(frozen=True)
class BatchTarget:
    task_id: str
    pr_id: int | None
    title: str
    method: str
    stage: str
    run_id: str
    mode: str | None
    state: str
    attempt: int | None
    execution: Path | None
    error: str | None = None
    target_key: str | None = None
    target_id: str | None = None
    seal: dict[str, str] | None = None
    view_sha256: str | None = None


@dataclass(frozen=True)
class DatasetReference:
    prompt_record: dict[str, Any]
    prompt_records: tuple[dict[str, Any], ...]
    prompt_source: Path
    pr_record: dict[str, Any] | None
    gold_changes: tuple[dict[str, Any], ...]
    gold_source: Path | None


def bench_default() -> Path:
    return Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


DETECT_METRICS_VERSION = "detect-metrics-v2"


def detect_metrics(bench: Path, batch_id: str) -> dict[str, Any] | None:
    """The recorded Detect hit-rate report for a batch, or None.

    Optional by construction: ``batch/detect_metrics.py`` writes it under ``Log/``
    and every batch card renders without it. ``load_json`` already answers None
    for each way it can be missing, so the only thing added here is the version
    guard -- a future document whose fields mean something else must render as
    *absent*, not be misread through today's names.
    """
    document = load_json(bench / "Log" / "reports" / "detect-metrics" / f"{batch_id}.json")
    if not document or document.get("metric_definition_version") != DETECT_METRICS_VERSION:
        return None
    if not isinstance(document.get("rows"), list) or not isinstance(document.get("methods"), list):
        return None
    return document


def _rate(value: Any) -> str:
    """A rate cell. Undefined renders as N/A, never 0%.

    An Agent that reported nothing has no precision. Printing 0.0% would read as
    "got everything wrong" and 100% as "perfect"; neither is a measurement.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return '<span class="source-path">N/A</span>'
    return f"{value * 100:.1f}%"


def _detect_counts(row: dict[str, Any]) -> str:
    """``a / b`` for one row, or N/A when the row was never scored."""
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else None
    if metrics is None:
        return _rate(None)
    return esc(f"{metrics.get('tp')} / {metrics.get('predicted_count')}")


def load_text(path: Path, limit: int = MAX_TEXT) -> str | None:
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        return None
    if b"\0" in data:
        return None
    value = data[:limit].decode("utf-8", errors="replace")
    if size > limit or len(data) > limit:
        value += f"\n\n[Viewer truncated this file after {limit:,} bytes.]\n"
    return value


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def is_experiment(path: Path) -> bool:
    if (path / "all-summary.json").is_file():
        return True
    return any(
        (path / variant).is_dir()
        and any((path / variant / item).exists() for item in ("state.json", "summary.json", "failure.json", "phases"))
        for variant in VARIANTS
    )


def _safe_child(root: Path, value: str) -> Path | None:
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or "\\" in value or "//" in value:
        return None
    candidate = root.joinpath(*pure.parts)
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return candidate


def _discover_legacy(bench: Path) -> list[Experiment]:
    log_root = bench / "Log"
    if not log_root.is_dir():
        return []
    log_real = log_root.resolve()
    found: dict[Path, Experiment] = {}
    for parent in log_root.rglob("experiments"):
        if not parent.is_dir():
            continue
        try:
            children = list(parent.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or not is_experiment(child):
                continue
            try:
                real = child.resolve(strict=True)
                real.relative_to(log_real)
                modified = child.stat().st_mtime
            except (OSError, ValueError):
                continue
            found[real] = Experiment(child.name, real, parent.parent.name, modified)
    return list(found.values())


def _discover_batches(bench: Path) -> list[Experiment]:
    configs = bench / "batch" / "pilot"
    runs = bench / "batch" / "runs"
    if not configs.is_dir() or not runs.is_dir():
        return []
    found: dict[str, Experiment] = {}
    for config_path in sorted(configs.glob("*.json")):
        if config_path.is_symlink() or not config_path.is_file():
            continue
        config = load_json(config_path)
        batch_id = config.get("batch_id") if config else None
        if not isinstance(batch_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", batch_id):
            continue
        run_root = runs / batch_id
        ledger = run_root / "ledger.jsonl"
        if run_root.is_symlink() or ledger.is_symlink() or not run_root.is_dir() or not ledger.is_file():
            continue
        try:
            run_root.resolve().relative_to(runs.resolve())
            modified = ledger.stat().st_mtime
        except (OSError, ValueError):
            continue
        candidate = Experiment(
            batch_id,
            run_root.resolve(),
            "batch",
            modified,
            source_kind="batch",
            config_path=config_path.resolve(),
            batch_id=batch_id,
        )
        previous = found.get(batch_id)
        if previous is None or str(candidate.config_path) < str(previous.config_path):
            found[batch_id] = candidate
    for manifest_path in sorted(runs.glob("*/prepared-round.json")):
        run_root = manifest_path.parent
        ledger = run_root / "ledger.jsonl"
        if (run_root.is_symlink() or manifest_path.is_symlink() or ledger.is_symlink() or not ledger.is_file()
                or not SAFE_TASK_ID.fullmatch(run_root.name)):
            continue
        found[run_root.name] = Experiment(run_root.name, run_root.resolve(), "batch", ledger.stat().st_mtime,
                                          source_kind="batch", config_path=manifest_path.resolve(), batch_id=run_root.name)
    for view_path in sorted(runs.glob("*/result-view.json")):
        view = load_json(view_path)
        if not view or view.get("view_type") != "TARGET_RESULT_VIEW":
            continue
        batch_id = view.get("batch_id")
        source = view.get("source")
        source_relative = source.get("path") if isinstance(source, dict) else None
        source_path = _safe_child(bench.parents[1], source_relative) if isinstance(source_relative, str) else None
        run_root = view_path.parent
        if not isinstance(batch_id, str) or not SAFE_TASK_ID.fullmatch(batch_id) or source_path is None or not source_path.is_file():
            continue
        found[batch_id] = Experiment(batch_id, run_root.resolve(), "batch", view_path.stat().st_mtime, source_kind="batch", config_path=source_path.resolve(), batch_id=batch_id)
    # Expand into per-PR views only after the duplicate-config dedupe above, so a
    # task never gains two cards from two configs describing the same batch.
    expanded: dict[str, Experiment] = {}
    for experiment in found.values():
        expanded[experiment.experiment_id] = experiment
        config = load_json(experiment.config_path) if experiment.config_path else None
        for task_id_value in _config_task_ids(config):
            view = replace(experiment, experiment_id=f"{experiment.batch_id}/{task_id_value}", task_id_filter=task_id_value)
            expanded.setdefault(view.experiment_id, view)
    return list(expanded.values())


def _config_task_ids(config: dict[str, Any] | None) -> list[str]:
    """Task ids eligible for their own card: well-formed and order-preserving deduped."""
    tasks = config.get("tasks") if config else None
    if not isinstance(tasks, list) and config and config.get("manifest_type") in {"PREPARED_EXPERIMENT", "PREPARED_ROUND"}:
        targets = config.get("targets")
        if not isinstance(targets, list):
            return []
        return list(dict.fromkeys(item["task_id"] for item in targets if isinstance(item, dict) and isinstance(item.get("task_id"), str) and SAFE_TASK_ID.fullmatch(item["task_id"])))
    if not isinstance(tasks, list):
        return []
    return list(
        dict.fromkeys(
            item["task_id"]
            for item in tasks
            if isinstance(item, dict) and isinstance(item.get("task_id"), str) and SAFE_TASK_ID.fullmatch(item["task_id"])
        )
    )


def discover(bench: Path) -> list[Experiment]:
    found = _discover_legacy(bench) + _discover_batches(bench)
    # Two stable passes: the first reproduces the historical id-descending tie-break,
    # the second only lifts whole-batch overviews above their own per-PR children.
    found.sort(key=lambda item: item.experiment_id, reverse=True)
    found.sort(key=lambda item: (-item.modified, 0 if item.task_id_filter is None else 1))
    return found


def _target_key(task_id: str, method: str, stage: str, run_id: str, mode: str | None) -> str:
    return ":".join((task_id, method, stage, run_id, mode or "none"))


def _batch_id(exp: Experiment) -> str:
    """The batch this experiment belongs to; falls back for hand-built Experiments."""
    return exp.batch_id or exp.experiment_id


def _batch_task_ids(exp: Experiment) -> list[str]:
    identifiers = _config_task_ids(load_json(exp.config_path) if exp.config_path else None)
    if exp.task_id_filter is not None:
        return [value for value in identifiers if value == exp.task_id_filter]
    return identifiers


def _ledger_events(exp: Experiment) -> tuple[list[dict[str, Any]], str | None]:
    ledger_path = exp.root / "ledger.jsonl"
    if ledger_path.is_symlink() or not ledger_path.is_file():
        return [], "ledger is missing or symlinked"
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return [], "ledger cannot be read"
    events: list[dict[str, Any]] = []
    previous = None
    for index, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return [], f"ledger event {index} is not valid JSON"
        if not isinstance(event, dict):
            return [], f"ledger event {index} is not an object"
        supplied = event.get("event_sha256")
        payload = dict(event)
        payload.pop("event_sha256", None)
        if (
            event.get("schema_version") != 1
            or event.get("batch_id") != _batch_id(exp)
            or event.get("sequence") != index
            or event.get("previous_event_sha256") != previous
            or not isinstance(supplied, str)
            or canonical_sha256(payload) != supplied
        ):
            return [], f"ledger hash chain is invalid at event {index}"
        previous = supplied
        events.append(event)
    return events, None


def _task_manifest(
    repository_root: Path, task_entry: dict[str, Any], task_id_value: str
) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    manifest_ref = task_entry.get("task_manifest")
    if not isinstance(manifest_ref, dict):
        return None, None, "task manifest reference is missing"
    relative_path = manifest_ref.get("path")
    expected_sha = manifest_ref.get("sha256")
    if not isinstance(relative_path, str) or not isinstance(expected_sha, str):
        return None, None, "task manifest reference is malformed"
    manifest_path = _safe_child(repository_root, relative_path)
    if manifest_path is None or manifest_path.is_symlink() or not manifest_path.is_file():
        return None, None, "task manifest path is unsafe or missing"
    if file_sha256(manifest_path) != expected_sha:
        return None, None, "task manifest hash does not match the batch config"
    task = load_json(manifest_path)
    if not task or task.get("task_id") != task_id_value:
        return None, None, "task manifest is missing or has a mismatched identity"
    return task, manifest_path, None


def _view_targets(exp: Experiment, bench: Path) -> list[BatchTarget] | None:
    view_path = exp.root / "result-view.json"
    if not view_path.is_file() and exp.config_path is None:
        return None
    # The page uses the same source, ledger, and seal checks as report generation.
    # Import here because the standalone tools script is also run outside PYTHONPATH.
    if str(bench) not in sys.path:
        sys.path.insert(0, str(bench))
    from batch.core import BatchError
    from batch.result_view import load as load_result_view, load_current_round

    repository_root = bench.parents[1]
    try:
        source = load_json(exp.config_path) if exp.config_path else None
        if source and source.get("manifest_type") == "PREPARED_ROUND":
            view = load_current_round(view_path, exp.config_path, bench, repository_root)
        elif view_path.is_file():
            view = load_result_view(view_path, bench, repository_root)
        else:
            return None
    except (BatchError, OSError, ValueError):
        return None
    if view["batch_id"] != _batch_id(exp):
        return None
    rows = view["targets"]
    order = view["target_order"]
    result = []
    for key in order:
        row = rows.get(key)
        if not isinstance(row, dict) or row.get("target_key") != key:
            return None
        if exp.task_id_filter is not None and row.get("task_id") != exp.task_id_filter:
            continue
        execution = None
        error = None
        state = row.get("state", "NOT_RECORDED")
        relative = row.get("execution_path")
        if state in TERMINAL_STATES and isinstance(relative, str):
            candidate = _safe_child(repository_root, relative)
            seal = row.get("seal")
            seal_relative = seal.get("path") if isinstance(seal, dict) else None
            seal_path = _safe_child(repository_root, seal_relative) if isinstance(seal_relative, str) else None
            if candidate is None or not candidate.is_dir() or candidate.is_symlink():
                error = "result view execution path is unsafe or missing"
            elif seal_path is None or seal_path.is_symlink() or not seal_path.is_file() or file_sha256(seal_path) != seal.get("sha256"):
                error = "result view seal reference is missing or changed"
            else:
                execution = candidate
        elif state not in TERMINAL_STATES:
            error = f"latest target state is {state}"
        result.append(BatchTarget(
            task_id=row.get("task_id", ""), pr_id=row.get("pr_id"), title=row.get("title", ""),
            method=row.get("method", ""), stage=row.get("stage", ""), run_id=row.get("run_id", ""),
            mode=row.get("mode"), state=state, attempt=row.get("attempt"), execution=execution, error=error,
            target_key=key, target_id=row.get("target_id"), seal=row.get("seal"), view_sha256=view["view_sha256"],
        ))
    return result


def batch_targets(exp: Experiment, bench: Path) -> list[BatchTarget]:
    indexed = _view_targets(exp, bench)
    if indexed is not None:
        return indexed
    if exp.source_kind != "batch" or exp.config_path is None:
        return []
    config = load_json(exp.config_path)
    if not config or config.get("batch_id") != _batch_id(exp):
        return []
    events, ledger_error = _ledger_events(exp)
    latest: dict[str, dict[str, Any]] = {}
    if ledger_error is None:
        for event in events:
            if event.get("state") == "SKIPPED_RESUME":
                continue
            target = event.get("target")
            if not isinstance(target, dict):
                continue
            values = tuple(target.get(name) for name in ("task_id", "method", "stage", "run_id"))
            if not all(isinstance(value, str) for value in values):
                continue
            mode = target.get("update_mode")
            if mode is not None and not isinstance(mode, str):
                continue
            latest[_target_key(*values, mode)] = event

    repository_root = bench.parents[1]
    results: list[BatchTarget] = []
    tasks = config.get("tasks")
    if not isinstance(tasks, list):
        return []
    for task_entry in tasks:
        if not isinstance(task_entry, dict) or not isinstance(task_entry.get("task_id"), str):
            continue
        task_id_value = task_entry["task_id"]
        # Per-PR scoping is a pure predicate. Never join this value onto a path: the
        # manifest and execution lookups below are what keep reads inside the bench.
        if exp.task_id_filter is not None and task_id_value != exp.task_id_filter:
            continue
        task, manifest_path, manifest_error = _task_manifest(repository_root, task_entry, task_id_value)
        task_root = manifest_path.parent if task and manifest_path else None
        pr_id = task.get("pr_id") if task and isinstance(task.get("pr_id"), int) else None
        title = task.get("title") if task and isinstance(task.get("title"), str) else ""
        methods = task_entry.get("methods")
        if not isinstance(methods, list):
            continue
        specifications: list[tuple[str, str, str, str | None]] = []
        for method_entry in methods:
            if not isinstance(method_entry, dict) or method_entry.get("method") not in VARIANTS:
                continue
            method = method_entry["method"]
            detect = method_entry.get("detect")
            if isinstance(detect, dict) and isinstance(detect.get("run_id"), str):
                specifications.append((method, "detect", detect["run_id"], None))
            updates = method_entry.get("updates")
            if isinstance(updates, list):
                for update in updates:
                    if not isinstance(update, dict) or not isinstance(update.get("run_id"), str):
                        continue
                    mode = update.get("mode")
                    if mode not in {"sealed-detect", "self-directed"}:
                        continue
                    specifications.append((method, "update", update["run_id"], mode))
        for method, stage, run_id, mode in specifications:
            key = _target_key(task_id_value, method, stage, run_id, mode)
            event = latest.get(key)
            state = str(event.get("state", "NOT_RECORDED")) if event else "NOT_RECORDED"
            attempt = event.get("attempt") if event and isinstance(event.get("attempt"), int) and event["attempt"] > 0 else None
            execution = None
            error = ledger_error or manifest_error
            if error is None and task_root is None:
                error = "task manifest is missing or has a mismatched identity"
            elif error is None and event is None:
                error = "target has no ledger event"
            elif error is None and (state not in TERMINAL_STATES or attempt is None):
                error = f"latest target state is {state}"
            elif error is None:
                candidate = task_root / "runs" / method / stage / "executions" / run_id / f"attempt-{attempt}"
                if stage == "update":
                    candidate = candidate / f"mode-{mode}"
                runs_root = task_root / "runs"
                try:
                    candidate.resolve().relative_to(runs_root.resolve())
                except (OSError, ValueError):
                    error = "execution path escapes the task run directory"
                else:
                    summary_name = "detect-summary.json" if stage == "detect" else "update-summary.json"
                    summary_path = candidate / summary_name
                    summary = load_json(summary_path) if not summary_path.is_symlink() else None
                    identity_ok = bool(
                        summary
                        and summary.get("task_id") == task_id_value
                        and summary.get("method") == method
                        and summary.get("status") == "SEALED"
                        and (stage == "detect" or summary.get("update_mode") == mode)
                    )
                    if candidate.is_symlink() or not candidate.is_dir() or not identity_ok:
                        error = "terminal execution summary is missing or has a mismatched identity"
                    else:
                        execution = candidate
            results.append(BatchTarget(
                task_id_value, pr_id, title, method, stage, run_id, mode,
                state, attempt, execution, error,
            ))
    return results


def variant_status(root: Path) -> tuple[str, dict[str, Any]]:
    failure = load_json(root / "failure.json")
    if failure:
        return "FAIL", failure
    summary = load_json(root / "summary.json")
    if summary:
        return str(summary.get("status", "UNKNOWN")), summary
    state = load_json(root / "state.json")
    if state:
        return str(state.get("status", "UNKNOWN")), state
    return "UNKNOWN", {}


def overall_status(exp: Experiment, bench: Path | None = None) -> str:
    if exp.source_kind == "batch":
        targets = batch_targets(exp, bench or bench_default())
        if not targets:
            return "INVALID"
        if all(item.state in TERMINAL_STATES and item.execution is not None for item in targets):
            return "SEALED"
        if any(item.state == "FAILED" for item in targets):
            return "INCOMPLETE"
        return "INCOMPLETE"
    summary = load_json(exp.root / "all-summary.json")
    if summary and summary.get("status"):
        return str(summary["status"])
    statuses = [variant_status(exp.root / item)[0] for item in VARIANTS if (exp.root / item).is_dir()]
    if not statuses:
        return "UNKNOWN"
    if "FAIL" in statuses or any(item in {"phase_failed", "validation_failed"} for item in statuses):
        return "FAIL"
    if "active" in statuses:
        return "INCOMPLETE"
    if len(set(statuses)) == 1:
        return statuses[0]
    return "MIXED"


def task_id(exp: Experiment) -> str:
    if exp.source_kind == "batch":
        values = _batch_task_ids(exp)
        return ", ".join(values)
    for variant in VARIANTS:
        value = load_json(exp.root / variant / "config.snapshot.json")
        if value and value.get("task_id"):
            return str(value["task_id"])
    return ""


def output_root(bench: Path) -> Path:
    configured = os.environ.get("SDD_RESULTS_OUTPUT_ROOT")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend((bench.parent.parent / "output", bench / "output"))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return candidates[0].resolve()


def experiment_identity(exp: Experiment) -> tuple[str | None, int | None]:
    if exp.source_kind == "batch":
        return None, None
    for variant in VARIANTS:
        value = load_json(exp.root / variant / "config.snapshot.json")
        if not value:
            continue
        sample = value.get("sample_id")
        pr_id = value.get("pr_id")
        return (sample if isinstance(sample, str) else None, pr_id if isinstance(pr_id, int) else None)
    return None, None


def find_prompt_record(root: Path, sample_id: str) -> tuple[dict[str, Any], Path] | None:
    prompt_root = root / "prompt"
    if not prompt_root.is_dir():
        return None
    for source in sorted(prompt_root.glob("*.json")):
        try:
            records = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and record.get("sample_id") == sample_id:
                return record, source
    return None


def find_pr_prompt_records(root: Path, repo: str, pr_id: int) -> tuple[dict[str, Any], ...]:
    prompt_root = root / "prompt"
    if not prompt_root.is_dir():
        return ()
    found: dict[str, dict[str, Any]] = {}
    for source in sorted(prompt_root.glob("*.json")):
        try:
            records = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or record.get("repo") != repo or record.get("pr_id") != pr_id:
                continue
            sample_id = record.get("sample_id")
            if isinstance(sample_id, str):
                found.setdefault(sample_id, record)
    return tuple(found[key] for key in sorted(found))


def find_pr_record(root: Path, record: dict[str, Any], pr_id: int | None) -> tuple[dict[str, Any] | None, Path | None]:
    repo = record.get("repo")
    if not isinstance(repo, str) or "/" not in repo or pr_id is None:
        return None, None
    raw_source = root / "raw_prs" / f"{repo.replace('/', '__')}.jsonl"
    try:
        stream = raw_source.open(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    with stream:
        for line in stream:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict) or raw.get("pr_id") != pr_id:
                continue
            return raw, raw_source
    return None, None


def pr_gold_changes(raw: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
    if not raw:
        return ()
    candidates: list[Any] = []
    changes = raw.get("test_changes")
    if isinstance(changes, list):
        candidates.extend(changes)
    pairs = raw.get("method_test_pairs")
    if isinstance(pairs, list):
        candidates.extend(pair.get("test_change") for pair in pairs if isinstance(pair, dict))
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for change in candidates:
        if not isinstance(change, dict):
            continue
        file_name = change.get("file")
        qualified_name = change.get("qualified_name")
        gold = change.get("gold_test")
        if not isinstance(file_name, str) or not isinstance(qualified_name, str) or not isinstance(gold, str):
            continue
        found.setdefault((file_name, qualified_name), change)
    return tuple(found[key] for key in sorted(found))


def dataset_reference(exp: Experiment, bench: Path) -> DatasetReference | None:
    sample_id, pr_id = experiment_identity(exp)
    if not sample_id:
        return None
    root = output_root(bench)
    located = find_prompt_record(root, sample_id)
    if not located:
        return None
    record, prompt_source = located
    repo = record.get("repo")
    effective_pr = pr_id if pr_id is not None else record.get("pr_id")
    prompt_records = (
        find_pr_prompt_records(root, repo, effective_pr)
        if isinstance(repo, str) and isinstance(effective_pr, int)
        else (record,)
    )
    raw, gold_source = find_pr_record(root, record, effective_pr if isinstance(effective_pr, int) else None)
    return DatasetReference(record, prompt_records or (record,), prompt_source, raw, pr_gold_changes(raw), gold_source)


def stamp(value: float) -> str:
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def resolve(experiments: list[Experiment], selector: str) -> Experiment:
    exact = [item for item in experiments if item.experiment_id == selector]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ViewerError(f"experiment {selector!r} occurs in multiple audit directories")
    matches = [item for item in experiments if item.experiment_id.endswith(selector) or selector in item.experiment_id]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ViewerError(f"no experiment matches {selector!r}")
    raise ViewerError(f"ambiguous selector {selector!r}: " + ", ".join(item.experiment_id for item in matches[:8]))


def _batch_present(exp: Experiment, bench: Path | None = None) -> list[str]:
    if exp.source_kind != "batch":
        return [name for name in VARIANTS if (exp.root / name).is_dir()]
    targets = batch_targets(exp, bench or bench_default())
    return [name for name in VARIANTS if any(item.method == name for item in targets)]


def choose(experiments: list[Experiment], bench: Path | None = None) -> Experiment:
    if not sys.stdin.isatty():
        raise ViewerError("an experiment id is required when stdin is not interactive")
    print("\nAvailable SDD experiments:\n")
    width = max((len(item.experiment_id) for item in experiments), default=32)
    for number, item in enumerate(experiments, 1):
        present = ", ".join(_batch_present(item, bench)) or "none"
        print(f"  {number:>2}. {item.experiment_id:<{width}} {overall_status(item, bench):<28} {present}")
    print()
    try:
        number = int(input("Select an experiment number: ").strip())
    except (EOFError, KeyboardInterrupt, ValueError) as error:
        raise ViewerError("no valid experiment selected") from error
    if not 1 <= number <= len(experiments):
        raise ViewerError("experiment number is out of range")
    return experiments[number - 1]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.") or "experiment"


def experiment_token(exp: Experiment) -> str:
    # Per-PR views share their parent's root, so the scope has to enter the identity
    # or every card in a batch would resolve to the same token (and 404).
    identity = f"{exp.source_kind}:{exp.root}"
    if exp.task_id_filter:
        identity += f":{exp.task_id_filter}"
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def status_class(value: str) -> str:
    upper = value.upper()
    if upper in {"PASS", "FINISHED", "SEALED", "READY", "COMPLETE"}:
        return "pass"
    if upper in {"FAIL", "PHASE_FAILED", "VALIDATION_FAILED", "INVALID"}:
        return "fail"
    if upper in {"AWAITING_MANUAL_REVIEW", "FINISHED_UNVERIFIED", "ACTIVE", "INCOMPLETE"}:
        return "pending"
    return "unknown"


def badge(value: str) -> str:
    return f'<span class="badge {status_class(value)}">{esc(value)}</span>'


def diff_name(block: str, number: int) -> str:
    first = block.splitlines()[0] if block else ""
    match = re.match(r"diff --git a/(.+?) b/(.+)$", first)
    if match:
        return match.group(2)
    for line in block.splitlines():
        if line.startswith("+++ b/"):
            return line[6:]
    return f"diff-{number}"


def split_diff(value: str) -> list[tuple[str, str]]:
    if not value.strip():
        return []
    starts = [match.start() for match in re.finditer(r"(?m)^diff --git ", value)]
    if not starts:
        return [("diff", value)]
    answer = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(value)
        block = value[start:end].rstrip() + "\n"
        answer.append((diff_name(block, index + 1), block))
    return answer


def diff_html(value: str) -> str:
    lines = []
    for line in value.splitlines():
        css = "ctx"
        if line.startswith("+") and not line.startswith("+++"):
            css = "add"
        elif line.startswith("-") and not line.startswith("---"):
            css = "del"
        elif line.startswith("@@"):
            css = "hunk"
        elif line.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file")):
            css = "meta"
        lines.append(f'<span class="line {css}">{esc(line)}</span>')
    return "\n".join(lines)


def diffs(root: Path) -> list[tuple[str, str]]:
    answer: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name in ("git.diff", "git-cached.diff"):
        value = load_text(root / name, MAX_DIFF)
        if not value:
            continue
        for file_name, block in split_diff(value):
            key = (file_name, hashlib.sha256(block.encode()).hexdigest())
            if key not in seen:
                seen.add(key)
                answer.append((file_name, block))
    return answer


def artifacts(root: Path) -> list[tuple[str, str]]:
    answer = []
    seen: set[Path] = set()
    for directory_name in ARTIFACT_DIRS:
        directory = root / directory_name
        if not directory.is_dir():
            continue
        try:
            paths = sorted(path for path in directory.rglob("*") if path.is_file())
        except OSError:
            continue
        for path in paths:
            try:
                real = path.resolve(strict=True)
                real.relative_to(directory.resolve())
            except (OSError, ValueError):
                continue
            if real in seen:
                continue
            value = load_text(path)
            if value is not None:
                seen.add(real)
                answer.append((str(path.relative_to(root)), value))
    for name in ("output-manifest.json", "artifact-manifest.json"):
        value = load_text(root / name)
        if value is not None:
            answer.append((name, value))
    return answer


def agent_messages(path: Path) -> list[str]:
    try:
        if path.stat().st_size > MAX_JSONL:
            return [f"[JSONL exceeds {MAX_JSONL:,} bytes and was not expanded.]"]
        stream = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return []
    answer = []
    with stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "item.completed":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    answer.append(item["text"])
            elif event.get("type") == "error" and isinstance(event.get("message"), str):
                answer.append("ERROR: " + event["message"])
            elif event.get("type") == "turn.failed" and isinstance(event.get("error"), dict):
                message = event["error"].get("message")
                if isinstance(message, str):
                    answer.append("TURN FAILED: " + message)
    return answer


def phase_outputs(root: Path) -> list[tuple[str, list[str]]]:
    directory = root / "phases"
    if not directory.is_dir():
        return []
    answer = []
    for path in sorted(directory.glob("*.jsonl")):
        messages = agent_messages(path)
        if messages:
            answer.append((path.name.removesuffix(".jsonl"), messages))
    return answer


def named_text_files(paths: list[Path], root: Path) -> list[tuple[str, str]]:
    answer = []
    for path in paths:
        value = load_text(path)
        if value and value.strip():
            answer.append((str(path.relative_to(root)), value))
    return answer


def prompts(root: Path) -> list[tuple[str, str]]:
    directory = root / "phases"
    return named_text_files(sorted(directory.glob("*.prompt.md")), root) if directory.is_dir() else []


def logs(root: Path) -> list[tuple[str, str]]:
    paths = [root / "all.stderr.log"]
    for directory, pattern in ((root / "validation", "*.log"), (root / "phases", "*.stderr.log")):
        if directory.is_dir():
            paths.extend(sorted(directory.glob(pattern)))
    return named_text_files(paths, root)


def changed(root: Path) -> list[str]:
    value = load_text(root / "changed-files.txt")
    return [line.rstrip() for line in value.splitlines() if line.strip()] if value else []


def code(value: str, css: str = "") -> str:
    return f'<pre class="code {css}">{esc(value)}</pre>'


def details(title: str, body: str, opened: bool = False) -> str:
    return f'<details class="panel"{" open" if opened else ""}><summary>{esc(title)}</summary>{body}</details>'


def render_variant(name: str, root: Path) -> tuple[str, list[tuple[str, str]]]:
    status, _ = variant_status(root)
    failure = load_json(root / "failure.json") or {}
    state = load_json(root / "state.json") or {}
    summary = load_json(root / "summary.json") or {}
    file_diffs = diffs(root)
    captured = artifacts(root)
    messages = phase_outputs(root)
    prompt_files = prompts(root)
    log_files = logs(root)
    changed_paths = changed(root)
    nav: list[tuple[str, str]] = []
    sections = []
    records = state.get("phase_records") if isinstance(state.get("phase_records"), list) else []
    facts = (
        ("Status", badge(status), True),
        ("Phases", f"{len(records)} recorded", False),
        ("LLM calls", summary.get("llm_call_count", len(records)), False),
        ("Validation", summary.get("validation_status", "not recorded"), False),
        ("Manual review", "required" if summary.get("manual_review_required") else "not recorded", False),
    )
    sections.append('<div class="facts">' + "".join(
        f'<div class="fact"><span>{esc(label)}</span><strong>{value if raw else esc(value)}</strong></div>'
        for label, value, raw in facts
    ) + "</div>")
    if failure:
        sections.append(
            '<section class="failure"><h3>Failure</h3>'
            f'<p><strong>Stage:</strong> {esc(failure.get("failed_stage", "unknown"))} &nbsp; '
            f'<strong>Exit:</strong> {esc(failure.get("exit_code", "unknown"))}</p>'
            f'<pre>{esc(failure.get("reason", "No failure reason was recorded."))}</pre></section>'
        )
    if changed_paths:
        sections.append('<section><h3>Changed files</h3><ul class="file-list">' + "".join(
            f"<li><code>{esc(item)}</code></li>" for item in changed_paths
        ) + "</ul></section>")
    if file_diffs:
        blocks = []
        for number, (file_name, value) in enumerate(file_diffs, 1):
            anchor = f"{name}-diff-{hashlib.sha1(file_name.encode()).hexdigest()[:10]}-{number}"
            nav.append((file_name, anchor))
            blocks.append(f'<article class="diff-file" id="{anchor}"><h4>{esc(file_name)}</h4><pre class="diff">{diff_html(value)}</pre></article>')
        sections.append("<section><h3>Code changes</h3>" + "".join(blocks) + "</section>")
    if captured:
        blocks = []
        for number, (file_name, value) in enumerate(captured, 1):
            anchor = f"{name}-artifact-{hashlib.sha1(file_name.encode()).hexdigest()[:10]}-{number}"
            nav.append((file_name, anchor))
            blocks.append(f'<div id="{anchor}">{details(file_name, code(value))}</div>')
        sections.append("<section><h3>Captured SDD artifacts</h3>" + "".join(blocks) + "</section>")
    if messages:
        sections.append("<section><h3>Agent output</h3>" + "".join(
            details(f"{phase} · {len(items)} Agent message(s)", "".join(f'<div class="agent-message">{code(item)}</div>' for item in items))
            for phase, items in messages
        ) + "</section>")
    if prompt_files:
        sections.append("<section><h3>Prompts</h3>" + "".join(details(name, code(value)) for name, value in prompt_files) + "</section>")
    if log_files:
        sections.append("<section><h3>Logs</h3>" + "".join(details(name, code(value)) for name, value in log_files) + "</section>")
    if len(sections) == 1:
        sections.append('<div class="empty">No additional output was captured for this SDD.</div>')
    header = (
        f'<div class="variant-heading"><div><p class="eyebrow">SDD output</p><h2>{esc(LABEL[name])}</h2></div>{badge(status)}</div>'
        f'<p class="source-path">Source: <code>{esc(root)}</code></p>'
    )
    return header + "".join(sections), nav


def render_overview(exp: Experiment, available: list[str]) -> str:
    rows = []
    for name in available:
        root = exp.root / name
        status, _ = variant_status(root)
        failure = load_json(root / "failure.json") or {}
        summary = load_json(root / "summary.json") or {}
        state = load_json(root / "state.json") or {}
        records = state.get("phase_records") if isinstance(state.get("phase_records"), list) else []
        rows.append(
            "<tr>" + f"<td><strong>{esc(LABEL[name])}</strong></td><td>{badge(status)}</td>"
            f"<td>{len(records)}</td><td>{esc(summary.get('validation_status', '—'))}</td>"
            f"<td>{esc(failure.get('failed_stage', '—'))}</td><td>{esc(failure.get('reason', '—'))}</td></tr>"
        )
    return (
        f'<div class="variant-heading"><div><p class="eyebrow">Experiment overview</p><h2>{esc(exp.experiment_id)}</h2></div>{badge(overall_status(exp, bench_default()))}</div>'
        '<div class="facts">'
        f'<div class="fact"><span>Task</span><strong>{esc(task_id(exp) or "not recorded")}</strong></div>'
        f'<div class="fact"><span>Updated</span><strong>{esc(stamp(exp.modified))}</strong></div>'
        f'<div class="fact"><span>Available SDDs</span><strong>{len(available)}</strong></div></div>'
        '<section><h3>Comparison</h3><div class="table-wrap"><table><thead><tr><th>SDD</th><th>Status</th><th>Phases</th><th>Validation</th><th>Failed stage</th><th>Reason</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div></section>'
        f'<p class="source-path">Experiment source: <code>{esc(exp.root)}</code></p>'
    )


def gold_change_diff(change: dict[str, Any]) -> str:
    file_name = str(change.get("file", "unknown-file"))
    qualified_name = str(change.get("qualified_name", "unknown-test"))
    old_test = change.get("old_test")
    gold_test = change.get("gold_test")
    if not isinstance(old_test, str) or not isinstance(gold_test, str):
        return ""
    return "\n".join(
        difflib.unified_diff(
            old_test.splitlines(),
            gold_test.splitlines(),
            fromfile=f"a/{file_name}::{qualified_name}",
            tofile=f"b/{file_name}::{qualified_name}",
            lineterm="",
        )
    )


def full_pr_patch(reference: DatasetReference) -> tuple[list[str], str]:
    raw = reference.pr_record
    if not raw:
        return [], ""
    names: list[str] = []
    blocks: list[str] = []
    changed_files = raw.get("changed_files")
    if not isinstance(changed_files, list):
        return names, ""
    for changed in changed_files:
        if not isinstance(changed, dict):
            continue
        file_name = changed.get("filename")
        patch = changed.get("patch")
        if not isinstance(file_name, str) or not isinstance(patch, str) or not patch.strip():
            continue
        names.append(file_name)
        blocks.append(
            f"diff --git a/{file_name} b/{file_name}\n"
            f"--- a/{file_name}\n"
            f"+++ b/{file_name}\n{patch.rstrip()}"
        )
    return names, "\n\n".join(blocks)


def pr_context_text(reference: DatasetReference) -> str:
    raw = reference.pr_record
    if not raw:
        return ""
    lines = [
        f"Repository: {raw.get('repo', 'not recorded')}",
        f"PR: {raw.get('pr_id', 'not recorded')}",
        f"URL: {raw.get('pr_url', 'not recorded')}",
        f"Title: {raw.get('title', 'not recorded')}",
        "",
        "Body:",
        str(raw.get("body") or "(empty)"),
    ]
    for heading, key in (
        ("Commit messages", "commit_messages"),
        ("Issue references", "body_issue_refs"),
        ("PR comments", "comments"),
        ("Review comments", "review_comments"),
    ):
        values = raw.get(key)
        if not isinstance(values, list) or not values:
            continue
        lines.extend(("", f"{heading}:"))
        for number, value in enumerate(values, 1):
            lines.append(f"[{number}] {value}")
    changed_files = raw.get("changed_files")
    if isinstance(changed_files, list) and changed_files:
        lines.extend(("", "Changed files:"))
        for changed in changed_files:
            if not isinstance(changed, dict):
                continue
            lines.append(
                f"- {changed.get('filename', 'unknown')} "
                f"({changed.get('status', 'unknown')}; +{changed.get('additions', '?')} "
                f"-{changed.get('deletions', '?')})"
            )
    return "\n".join(lines).rstrip() + "\n"


def render_reference(reference: DatasetReference) -> str:
    record = reference.prompt_record
    facts = (
        ("Repository", record.get("repo", "not recorded")),
        ("PR", record.get("pr_id", "not recorded")),
        ("Selected sample", record.get("sample_id", "not recorded")),
        ("PR samples", len(reference.prompt_records)),
        ("Gold test changes", len(reference.gold_changes)),
    )
    sections = [
        '<div class="variant-heading"><div><p class="eyebrow">PR-level dataset reference</p><h2>PR prompts, gold tests &amp; diffs</h2></div><span class="badge pending">HUMAN ONLY</span></div>',
        '<p class="gold-warning">Gold is loaded only by this host-side viewer. It is not copied into Agent prompts or experiment repositories.</p>',
        '<div class="facts">' + "".join(f'<div class="fact"><span>{esc(name)}</span><strong>{esc(value)}</strong></div>' for name, value in facts) + '</div>',
    ]
    context = pr_context_text(reference)
    if context:
        sections.append('<section><h3>Complete PR context</h3>' + details("Title, body, comments, commits, and changed files", code(context), True) + '</section>')
    prompt_blocks = []
    for prompt_record in reference.prompt_records:
        prompt = prompt_record.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        label = f"{prompt_record.get('sample_id', 'unknown sample')} · {prompt_record.get('old_test_qualified_name', 'unknown test')}"
        prompt_blocks.append(details(label, code(prompt), prompt_record.get("sample_id") == record.get("sample_id")))
    if prompt_blocks:
        sections.append('<section><h3>All dataset prompts for this PR</h3><p class="source-path">Human-only source records; these full generated prompts are not the sanitized Agent input.</p>' + "".join(prompt_blocks) + '</section>')
    gold_blocks = []
    for change in reference.gold_changes:
        file_name = str(change.get("file", "unknown file"))
        qualified_name = str(change.get("qualified_name", "unknown test"))
        old_test = change.get("old_test")
        gold_test = change.get("gold_test")
        difference = gold_change_diff(change)
        content = f'<p class="source-path">File: <code>{esc(file_name)}</code></p>'
        if isinstance(old_test, str) and old_test.strip():
            content += details("Original test", code(old_test))
        if isinstance(gold_test, str) and gold_test.strip():
            content += details("Developer-merged gold test", code(gold_test), True)
        if difference:
            content += details("Gold unified diff", f'<pre class="diff">{diff_html(difference)}</pre>', True)
        gold_blocks.append(details(f"{qualified_name} · {file_name}", content, True))
    if gold_blocks:
        sections.append('<section><h3>All gold tests and gold diffs for this PR</h3>' + "".join(gold_blocks) + '</section>')
    patch_names, patch = full_pr_patch(reference)
    if patch:
        sections.append('<section><h3>Complete developer PR patch</h3><p class="source-path">Files: ' + esc(", ".join(patch_names)) + '</p><pre class="diff">' + diff_html(patch) + '</pre></section>')
    sections.append(f'<p class="source-path">Prompt source: <code>{esc(reference.prompt_source)}</code></p>')
    if reference.gold_source:
        sections.append(f'<p class="source-path">Gold source: <code>{esc(reference.gold_source)}</code></p>')
    return "".join(sections)


def comparison_sources(exp: Experiment, reference: DatasetReference | None) -> list[tuple[str, str, list[str], str]]:
    sources = []
    for variant in VARIANTS:
        root = exp.root / variant
        blocks = diffs(root) if root.is_dir() else []
        if blocks:
            value = "\n".join(block for _, block in blocks)
            sources.append((
                f"source-{variant}",
                f"{LABEL[variant]} code diff",
                [file_name for file_name, _ in blocks],
                value,
            ))
    if reference:
        pr_id = reference.prompt_record.get("pr_id", "unknown")
        context = pr_context_text(reference)
        if context:
            sources.append(("source-pr-context", f"PR {pr_id} complete context", [], context))
        patch_names, patch = full_pr_patch(reference)
        if patch:
            sources.append(("source-pr-full-patch", f"PR {pr_id} complete developer patch", patch_names, patch))
        gold_diffs: list[str] = []
        gold_files: list[str] = []
        originals: list[str] = []
        gold_tests: list[str] = []
        for number, change in enumerate(reference.gold_changes, 1):
            file_name = str(change.get("file", "unknown file"))
            qualified_name = str(change.get("qualified_name", "unknown test"))
            display_file = f"{file_name}::{qualified_name}"
            difference = gold_change_diff(change)
            old_test = change.get("old_test")
            gold_test = change.get("gold_test")
            if difference:
                gold_diffs.append(difference)
                gold_files.append(file_name)
                sources.append((f"source-gold-diff-{number}", f"Gold diff · {qualified_name}", [display_file], difference))
            if isinstance(old_test, str) and old_test.strip():
                originals.append(f"# {display_file}\n\n{old_test.rstrip()}")
            if isinstance(gold_test, str) and gold_test.strip():
                gold_tests.append(f"# {display_file}\n\n{gold_test.rstrip()}")
                sources.append((f"source-gold-test-{number}", f"Gold test · {qualified_name}", [display_file], gold_test))
        if gold_diffs:
            sources.append(("source-pr-gold-diffs", f"PR {pr_id} all gold test diffs", sorted(set(gold_files)), "\n\n".join(gold_diffs)))
        if originals:
            sources.append(("source-pr-original-tests", f"PR {pr_id} all original tests", sorted(set(gold_files)), "\n\n".join(originals)))
        if gold_tests:
            sources.append(("source-pr-gold-tests", f"PR {pr_id} all gold tests", sorted(set(gold_files)), "\n\n".join(gold_tests)))
    return sources


def render_comparison(sources: list[tuple[str, str, list[str], str]]) -> str:
    keys = [key for key, _, _, _ in sources]
    left_key = keys[0]
    right_key = next((key for key in ("source-pr-full-patch", "source-pr-gold-diffs", "source-pr-gold-tests") if key in keys), keys[1])
    files = {key: names for key, _, names, _ in sources}
    values = {key: value for key, _, _, value in sources}

    def options(selected: str) -> str:
        return "".join(
            f'<option value="{esc(key)}"{" selected" if key == selected else ""}>'
            f'{esc(label)} · {esc(", ".join(names))}</option>'
            for key, label, names, _ in sources
        )

    hidden = "".join(
        f'<pre class="compare-source" id="{esc(key)}" data-files="{esc(", ".join(names))}">{esc(value)}</pre>'
        for key, _, names, value in sources
    )
    return (
        '<div class="variant-heading"><div><p class="eyebrow">Side-by-side review</p><h2>Compare outputs</h2></div><span class="badge pending">MANUAL REVIEW</span></div>'
        '<p class="source-path">Choose any two SDD outputs, the complete PR context/patch, or PR-wide and per-test gold sources.</p>'
        '<div class="compare-grid">'
        f'<section class="compare-pane"><select class="compare-select" data-target="compare-left" data-file-target="compare-left-files">{options(left_key)}</select>'
        f'<div class="compare-file" id="compare-left-files">File: {esc(", ".join(files[left_key]))}</div>'
        f'<pre class="compare-code" id="compare-left">{esc(values[left_key])}</pre></section>'
        f'<section class="compare-pane"><select class="compare-select" data-target="compare-right" data-file-target="compare-right-files">{options(right_key)}</select>'
        f'<div class="compare-file" id="compare-right-files">File: {esc(", ".join(files[right_key]))}</div>'
        f'<pre class="compare-code" id="compare-right">{esc(values[right_key])}</pre></section>'
        '</div><div hidden>' + hidden + '</div>'
    )


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDD Results · __TITLE__</title><style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2d;--panel2:#182238;--line:#293754;--text:#e8edf7;--muted:#9eabc2;--blue:#73a7ff;--green:#77d49b;--red:#ff8795;--amber:#f4c76d}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:linear-gradient(145deg,#080d19,#10182a 55%,#0b1221);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}button,a{font:inherit}.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:18px;padding:14px 24px;background:rgba(9,14,27,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}.brand{min-width:max-content;font-weight:800;letter-spacing:.04em}.tabs{display:flex;gap:8px;overflow:auto}.tab-button{color:var(--muted);background:transparent;border:1px solid transparent;border-radius:9px;padding:8px 13px;cursor:pointer}.tab-button:hover,.tab-button.active{color:white;background:var(--panel2);border-color:var(--line)}.layout{display:grid;grid-template-columns:230px minmax(0,1fr);max-width:1600px;margin:0 auto}.sidebar{position:sticky;top:67px;align-self:start;height:calc(100vh - 67px);overflow:auto;padding:24px 16px;border-right:1px solid var(--line)}.sidebar h3{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.12em}.nav-group{display:none}.nav-group.active{display:block}.nav-group a{display:block;color:#cbd6e9;text-decoration:none;padding:7px 8px;border-radius:7px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.nav-group a:hover{color:white;background:var(--panel2)}.content{min-width:0;padding:30px clamp(18px,4vw,60px) 80px}.tab-pane{display:none}.tab-pane.active{display:block}.variant-heading{display:flex;justify-content:space-between;align-items:end;gap:20px}.eyebrow{margin:0 0 3px;color:var(--blue);text-transform:uppercase;letter-spacing:.14em;font-size:11px;font-weight:800}h2{font-size:30px;margin:0}h3{margin:28px 0 12px}h4{margin:0;padding:12px 16px;background:#172136;border-bottom:1px solid var(--line)}.source-path{color:var(--muted);overflow-wrap:anywhere}.badge{display:inline-flex;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:800;letter-spacing:.035em}.badge.pass{color:var(--green);background:#173426}.badge.fail{color:var(--red);background:#3a1921}.badge.pending{color:var(--amber);background:#382e17}.badge.unknown{color:var(--muted);background:#242d40}.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0}.fact{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:13px 15px}.fact span{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}.fact strong{overflow-wrap:anywhere}.failure{background:#2a151c;border:1px solid #6f2b38;border-radius:12px;padding:0 18px 16px}.failure pre{color:#ffd4d9;white-space:pre-wrap}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px}table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em}.file-list{columns:2;padding-left:22px}.file-list li{margin:5px 0;break-inside:avoid}.diff-file{margin:0 0 18px;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#0a0f1b;scroll-margin-top:84px}pre{overflow:auto}.diff,.code{margin:0;padding:16px;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;tab-size:4}.line{display:block;min-height:1.55em;white-space:pre}.line.add{color:#b9f5cb;background:#102b1d}.line.del{color:#ffc0c7;background:#32171e}.line.hunk{color:#a9c9ff;background:#142542}.line.meta{color:#c3b4ff;font-weight:700}details.panel{margin:10px 0;border:1px solid var(--line);border-radius:10px;background:var(--panel);overflow:hidden}details.panel summary{cursor:pointer;padding:11px 14px;font-weight:700;background:var(--panel2)}.agent-message+.agent-message{border-top:1px solid var(--line)}.empty{color:var(--muted);padding:30px;text-align:center;border:1px dashed var(--line);border-radius:12px}.footer{margin-top:50px;color:var(--muted);font-size:12px}.gold-warning{color:#ffe1a3;background:#322817;border:1px solid #705724;border-radius:10px;padding:12px 14px}.compare-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;margin-top:22px}.compare-pane{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.compare-select{width:100%;color:var(--text);background:var(--panel2);border:0;border-bottom:1px solid var(--line);padding:12px 14px;font:inherit;font-weight:700}.compare-file{color:var(--muted);background:#0f1728;border-bottom:1px solid var(--line);padding:8px 14px;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere}.compare-code{height:70vh;min-height:440px;margin:0;padding:16px;overflow:auto;white-space:pre;tab-size:4;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.compare-source{display:none}@media(max-width:850px){.layout{grid-template-columns:1fr}.sidebar{display:none}.topbar{align-items:flex-start;flex-direction:column;gap:8px}.content{padding-top:22px}.file-list{columns:1}.compare-grid{grid-template-columns:1fr}.compare-code{height:52vh}}
</style></head><body><header class="topbar"><div class="brand">SDD Results <small>v__VERSION__</small></div><nav class="tabs">__TABS__</nav></header><div class="layout"><aside class="sidebar">__NAV__</aside><div class="content">__PANES__<div class="footer">Generated __GENERATED__ · Source results were not modified.</div></div></div><script>
const buttons=[...document.querySelectorAll('.tab-button')];function selectTab(name){buttons.forEach(b=>b.classList.toggle('active',b.dataset.tab===name));document.querySelectorAll('.tab-pane').forEach(p=>p.classList.toggle('active',p.id==='tab-'+name));document.querySelectorAll('.nav-group').forEach(n=>n.classList.toggle('active',n.dataset.nav===name));history.replaceState(null,'','#'+name)}buttons.forEach(b=>b.addEventListener('click',()=>selectTab(b.dataset.tab)));const initial=location.hash.slice(1);if(buttons.some(b=>b.dataset.tab===initial))selectTab(initial);document.querySelectorAll('.compare-select').forEach(select=>select.addEventListener('change',()=>{const source=document.getElementById(select.value),target=document.getElementById(select.dataset.target),fileTarget=document.getElementById(select.dataset.fileTarget);if(source&&target)target.textContent=source.textContent;if(source&&fileTarget)fileTarget.textContent='File: '+source.dataset.files}));
</script></body></html>"""


def _text_panel(path: Path, root: Path, title: str | None = None, opened: bool = False) -> str:
    value = load_text(path)
    if value is None:
        return ""
    try:
        name = str(path.relative_to(root))
    except ValueError:
        name = path.name
    return details(title or name, code(value), opened)


def _batch_target_anchor(target: BatchTarget) -> str:
    raw = _target_key(target.task_id, target.method, target.stage, target.run_id, target.mode)
    return "target-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _batch_target_html(target: BatchTarget) -> tuple[str, list[tuple[str, str]]]:
    anchor = _batch_target_anchor(target)
    label = f"{LABEL[target.method]} · {target.stage}"
    if target.mode:
        label += f" · {target.mode}"
    facts = (
        ("Status", badge(target.state), True),
        ("Run", target.run_id, False),
        ("Attempt", target.attempt if target.attempt is not None else "—", False),
        ("Mode", target.mode or "—", False),
    )
    if target.execution is not None:
        _, read_usage = _token_tools()
        log = target.execution / ('agent.jsonl' if target.stage == 'detect' else 'artifacts/agent.jsonl')
        usage = read_usage(log)
        facts += (("Latest attempt tokens", _token_number(usage['total_tokens']), False),)
    parts = [
        f'<article class="batch-target" id="{anchor}">',
        f'<div class="variant-heading"><div><p class="eyebrow">{esc(target.stage)} result</p><h3>{esc(label)}</h3></div>{badge(target.state)}</div>',
        '<div class="facts">' + "".join(
            f'<div class="fact"><span>{esc(name)}</span><strong>{value if raw else esc(value)}</strong></div>'
            for name, value, raw in facts
        ) + "</div>",
    ]
    if target.error or target.execution is None:
        parts.append(f'<section class="failure"><h3>Unavailable</h3><pre>{esc(target.error or "no sealed execution")}</pre></section></article>')
        return "".join(parts), [(label, anchor)]

    root = target.execution
    if target.stage == "detect":
        manifest = load_json(root / "detection-manifest.json")
        candidates = manifest.get("candidates") if manifest else None
        if isinstance(candidates, list):
            blocks = []
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                symbols = candidate.get("symbols") if isinstance(candidate.get("symbols"), list) else []
                blocks.append(
                    f'<div class="fact"><span>{esc(candidate.get("path", "unknown"))}</span>'
                    f'<strong>{esc(", ".join(str(item) for item in symbols) or "no symbols")}</strong>'
                    f'<p>{esc(candidate.get("reason", ""))}</p></div>'
                )
            if blocks:
                parts.append('<section><h3>Detected candidates</h3><div class="facts">' + "".join(blocks) + "</div></section>")
        files = [root / "detection-manifest.json", root / "detect-summary.json"]
        documents = "".join(_text_panel(path, root) for path in files if path.is_file() and not path.is_symlink())
        if documents:
            parts.append("<section><h3>Sealed manifests</h3>" + documents + "</section>")
        sdd_root = root / "sdd-artifacts"
        if sdd_root.is_dir() and not sdd_root.is_symlink():
            artifact_blocks = []
            for path in sorted(sdd_root.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    panel = _text_panel(path, root)
                    if panel:
                        artifact_blocks.append(panel)
            if artifact_blocks:
                parts.append("<section><h3>SDD planning artifacts</h3>" + "".join(artifact_blocks) + "</section>")
        transcript = root / "agent.jsonl"
    else:
        patch_path = root / "artifacts" / "candidate.patch"
        patch = load_text(patch_path, MAX_DIFF) if patch_path.is_file() and not patch_path.is_symlink() else None
        if patch:
            blocks = []
            for number, (file_name, value) in enumerate(split_diff(patch), 1):
                diff_anchor = f"{anchor}-diff-{number}"
                blocks.append(f'<article class="diff-file" id="{diff_anchor}"><h4>{esc(file_name)}</h4><pre class="diff">{diff_html(value)}</pre></article>')
            parts.append("<section><h3>Candidate patch</h3>" + "".join(blocks) + "</section>")
        files = [
            root / "candidate-modified-files.json",
            root / "artifacts" / "scope-audit.json",
            root / "update-summary.json",
        ]
        documents = "".join(_text_panel(path, root) for path in files if path.is_file() and not path.is_symlink())
        if documents:
            parts.append("<section><h3>Update artifacts</h3>" + documents + "</section>")
        transcript = root / "artifacts" / "agent.jsonl"
    if transcript.is_file() and not transcript.is_symlink():
        messages = agent_messages(transcript)
        if messages:
            parts.append("<section><h3>Agent output</h3>" + details(
                f"{len(messages)} Agent message(s)",
                "".join(f'<div class="agent-message">{code(item)}</div>' for item in messages),
            ) + "</section>")
    parts.append(f'<p class="source-path">Sealed source: <code>{esc(root)}</code></p></article>')
    return "".join(parts), [(label, anchor)]


def _batch_method_section(method: str, items: list[BatchTarget]) -> tuple[str, list[tuple[str, str]]]:
    sections = [f'<section><h3>{esc(LABEL[method])}</h3>']
    links: list[tuple[str, str]] = []
    for target in items:
        target_html, target_links = _batch_target_html(target)
        sections.append(target_html)
        links.extend(target_links)
    sections.append("</section>")
    return "".join(sections), links


def _dedupe_targets(targets: list[BatchTarget]) -> list[BatchTarget]:
    """Anchor ids must stay unique; a config listing one task twice would collide."""
    seen: set[str] = set()
    unique: list[BatchTarget] = []
    for target in targets:
        anchor = _batch_target_anchor(target)
        if anchor in seen:
            continue
        seen.add(anchor)
        unique.append(target)
    return unique


def _token_number(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else "未记录"


def _token_tools():
    if str(bench_default()) not in sys.path:
        sys.path.insert(0, str(bench_default()))
    from batch.token_usage import aggregate, read_usage
    return aggregate, read_usage


def batch_token_usage(exp: Experiment, targets: list[BatchTarget], bench: Path) -> dict[str, Any]:
    """Include every ledger-referenced formal attempt, even failed attempts.

    Read-only for old and new runs. No filesystem glob may invent an attempt or
    make another round's workspace contribute to this round's cost.
    """
    aggregate, read_usage = _token_tools()
    from batch.token_usage import missing
    events, ledger_error = _ledger_events(exp)
    if ledger_error:
        return {'summary': aggregate([]), 'rows': [], 'error': ledger_error}
    config = load_json(exp.config_path) if exp.config_path else None
    entries = (config.get('targets') or config.get('tasks') or []) if config else []
    roots = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get('task_id')
        if not isinstance(identifier, str) or identifier in roots:
            continue
        task, path, error = _task_manifest(bench.parents[1], entry, identifier)
        if task and path and not error:
            roots[identifier] = path.parent
    attempts = {}
    for event in events:
        target = event.get('target', {})
        if event.get('action') not in {'detect', 'update'} or event.get('state') == 'SKIPPED_RESUME':
            continue
        if not isinstance(target, dict) or target.get('stage') != event.get('action'):
            continue
        names = [target.get(k) for k in ('task_id', 'method', 'stage', 'run_id')]
        if not all(isinstance(n, str) and SAFE_TASK_ID.fullmatch(n) for n in names):
            continue
        mode = target.get('update_mode')
        key = _target_key(*names, mode)
        attempt = event.get('attempt')
        if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0:
            attempts.setdefault(key, {})[attempt] = event.get('state')
    rows = []
    for target in targets:
        key = _target_key(target.task_id, target.method, target.stage, target.run_id, target.mode)
        for number, state in sorted(attempts.get(key, {}).items()):
            task_root = roots.get(target.task_id)
            usage = missing()
            log_relative = None
            if task_root is not None:
                relative = f'runs/{target.method}/{target.stage}/executions/{target.run_id}/attempt-{number}'
                if target.stage == 'update':
                    relative += f'/mode-{target.mode}/artifacts'
                log = _safe_child(task_root, relative + '/agent.jsonl')
                if log is not None and not log.is_symlink():
                    usage = read_usage(log)
                    log_relative = log.relative_to(bench.parents[1]).as_posix()
            rows.append({'target_key': key, 'task_id': target.task_id, 'method': target.method,
                         'stage': target.stage, 'mode': target.mode, 'run_id': target.run_id,
                         'attempt': number, 'state': state, 'latest': number == target.attempt,
                         'log_path': log_relative, 'usage': usage})
    rows.sort(key=lambda row: (row['target_key'], row['attempt']))
    return {'summary': aggregate(row['usage'] for row in rows), 'rows': rows, 'error': None}


def _usage_table(document: dict[str, Any]) -> str:
    aggregate, _ = _token_tools()
    summary, rows = document['summary'], document['rows']
    statuses = {'RECORDED': '完整', 'PARTIAL': '部分记录', 'NOT_RECORDED': '未记录', 'UNREADABLE': '无法读取'}
    if document.get('error'):
        return '<section><h3>Token 用量</h3><p>无法核对用量：' + esc(document['error']) + '</p></section>'
    body, groups = [], []
    for method in VARIANTS:
        members = [row for row in rows if row['method'] == method]
        if not members:
            continue
        total = aggregate(row['usage'] for row in members)
        groups.append(f'<tr><td>{esc(LABEL[method])}</td>' + ''.join(
            f'<td>{_token_number(total[field])}</td>' for field in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens'))
            + f'<td>{total["recorded_attempt_count"]}/{total["attempt_count"]}</td><td>{statuses[total["status"]]}</td></tr>')
    for row in rows:
        usage = row['usage']
        body.append(f'<tr><td>{esc(row["task_id"])}</td><td>{esc(LABEL[row["method"]])}</td>'
            f'<td>{esc(row["stage"])} {esc(row.get("mode") or "")}</td><td>{esc(row["run_id"])} · attempt {row["attempt"]}{"（最新）" if row["latest"] else ""}</td>'
            f'<td>{esc(row["state"])}</td>' + ''.join(f'<td>{_token_number(usage[field])}</td>' for field in ('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens'))
            + f'<td>{esc(statuses.get(usage["status"], usage["status"]))}</td></tr>')
    return ('<section><h3>Token 用量（含全部重试与失败尝试）</h3><div class="facts">'
        + ''.join(f'<div class="fact"><span>{title}</span><strong>{_token_number(summary[field])}</strong></div>' for field,title in (
            ('input_tokens','已记录输入 token'),('cached_input_tokens','其中缓存输入'),('output_tokens','已记录输出 token'),('total_tokens','已记录总 token')))
        + '</div>' + f'<p>状态：{statuses[summary["status"]]} · 有用量记录 {summary["recorded_attempt_count"]}/{summary["attempt_count"]} 次尝试 · 缺失 {summary["missing_attempt_count"]} · 部分记录 {summary["partial_attempt_count"]}</p>'
        + '<p class="source-path">总量 = 输入 + 输出；缓存输入已包含在输入中，推理输出已包含在输出中，不重复相加。部分记录仅为已知小计，未记录不等于零。Token 数不是费用。</p>'
        + ('<div class="table-wrap"><table><thead><tr><th>方法</th><th>输入</th><th>缓存输入</th><th>输出</th><th>推理输出</th><th>合计</th><th>记录/尝试</th><th>状态</th></tr></thead><tbody>' + ''.join(groups) + '</tbody></table></div>' if groups else '<p>暂无已记录的模型用量。</p>')
        + details('每次尝试的 token 用量', '<div class="table-wrap"><table><thead><tr><th>Task / Phase</th><th>方法</th><th>阶段 / 模式</th><th>Run / 尝试</th><th>状态</th><th>输入</th><th>缓存输入</th><th>输出</th><th>推理输出</th><th>合计</th><th>用量记录</th></tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>')
        + '</section>')


def _legacy_token_usage(exp: Experiment) -> dict[str, Any]:
    aggregate, read_usage = _token_tools()
    rows = []
    for method in VARIANTS:
        directory = exp.root / method / 'phases'
        if directory.is_symlink():
            continue
        for log in sorted(directory.glob('*.jsonl')):
            if log.is_symlink() or not log.resolve().is_relative_to(exp.root.resolve()):
                continue
            rows.append({'task_id': log.stem, 'method': method, 'stage': 'legacy-phase', 'mode': None,
                         'run_id': log.stem, 'attempt': 1, 'latest': True, 'state': '历史阶段日志',
                         'usage': read_usage(log)})
    return {'summary': aggregate(row['usage'] for row in rows), 'rows': rows, 'error': None}


@lru_cache(maxsize=16)
def _validated_testcase_metrics(content: bytes, schema_content: bytes) -> dict[str, Any] | None:
    """Cache expensive schema validation by exact report AND schema bytes."""
    try:
        document = json.loads(content)
        if not isinstance(document, dict) or document.get('metric_definition_version') != 'detect-metrics-v3':
            return None
        payload = dict(document)
        supplied = payload.pop('metric_set_sha256', None)
        if canonical_sha256(payload) != supplied:
            return None
        if not isinstance(document.get('rows'), list) or not isinstance(document.get('methods'), list):
            return None
        from jsonschema import Draft202012Validator
        if next(Draft202012Validator(json.loads(schema_content)).iter_errors(document), None) is not None:
            return None
        return document
    except (UnicodeError, TypeError, ValueError):
        return None


def testcase_metrics(bench: Path, batch_id: str) -> dict[str, Any] | None:
    """Read numeric host summary; changed bytes always invalidate validation."""
    try:
        path = bench / 'Log/reports/testcase-metrics' / f'{batch_id}.json'
        schema = bench / 'schemas/detect-metrics-v3.schema.json'
        if path.is_symlink() or schema.is_symlink():
            return None
        document = _validated_testcase_metrics(path.read_bytes(), schema.read_bytes())
        return copy.deepcopy(document)
    except OSError:
        return None


def _testcase_table(bench: Path, batch_id: str, task_id: str | None = None, *, targets: list[BatchTarget] | None = None) -> str:
    document = testcase_metrics(bench, batch_id)
    command = f"python3 bin/sdd-detect-metrics check --batch {batch_id} --testcase"
    if document is None:
        report_path = bench / 'Log/reports/testcase-metrics' / f'{batch_id}.json'
        reason = '尚未生成双粒度评分' if not report_path.exists() else '双粒度报告无法读取、版本不支持或校验失败'
        return '<section><h3>文件级 / testcase 级指标</h3><p>' + reason + '。在宿主机执行：</p><code>' + esc(command) + '</code><p>页面只读，不自动调用模型或读取 gold 评分。</p></section>'
    if targets is not None:
        hashes = {t.view_sha256 for t in targets if t.view_sha256}
        current = {_target_key(t.task_id,t.method,t.stage,t.run_id,t.mode):t for t in targets if t.stage == 'detect'}
        reported = [r for r in document['rows'] if task_id is None or r['task_id'] == task_id]
        changed = bool(hashes and hashes != {document['result_view_sha256']}) or any(t.error and t.state in TERMINAL_STATES for t in targets)
        changed = changed or len(current) != len(reported) or any(
            r['target_key'] not in current or (current[r['target_key']].state, current[r['target_key']].attempt) != (r['state'],r['attempt'])
            for r in reported)
        if changed:
            return '<section><h3>文件级 / testcase 级指标</h3><p>评分已过期：运行状态或 ledger 已变化，请重新进行宿主机评分。</p><code>' + esc(command) + '</code></section>'
    body = []
    # Public pages render counts only. Gold identities and snippets stay host-only.
    for row in document['rows']:
        if task_id is not None and row['task_id'] != task_id:
            continue
        for level, title in (("legacy_file", "历史文件级"), ("scoped_file", "同范围文件级"), ("testcase", "testcase 级")):
            metric = row.get(level) or {}
            if row['status'] == 'NO_POSITIVE_GOLD' and level == 'testcase':
                metric = {'predicted_count': row.get('false_alarm_count', 0), 'gold_count': 0, 'tp': 0}
            body.append(f'<tr><td>{esc(row["task_id"])}</td><td>{esc(LABEL.get(row["method"], row["method"]))}</td>'
                        f'<td>{title}</td><td>{esc(metric.get("predicted_count", "—"))}</td>'
                        f'<td>{esc(metric.get("gold_count", "—"))}</td><td>{esc(metric.get("tp", "—"))}</td>'
                        f'<td>{_rate(metric.get("precision"))}</td><td>{_rate(metric.get("recall"))}</td>'
                        f'<td>{_rate(metric.get("f1"))}</td><td>{esc(row["status"])}</td></tr>')
    summary = []
    if task_id is None:
        for method in document['legacy_file_methods']:
            summary.append(f'<tr><td>{esc(LABEL.get(method["method"], method["method"]))}</td><td>历史文件级</td>'
                f'<td>{esc(method["scorable_count"])}/{esc(method["row_count"])}</td>'
                + ''.join(f'<td>{_rate(method[k])}</td>' for k in ('hit_rate_micro','recall_micro','f1_micro','hit_rate_macro','recall_macro','f1_macro')) + '</tr>')
        for method in document['methods']:
            for level, title in (("scoped_file", "同范围文件级"), ("testcase", "testcase 级"), ("successful_testcase", "仅成功 testcase（条件分数）")):
                metric = method[level]
                summary.append(f'<tr><td>{esc(LABEL.get(method["method"], method["method"]))}</td><td>{title}</td>'
                    f'<td>{esc(metric["scored_count"])}/{esc(method["row_count"])}</td>'
                    + ''.join(f'<td>{_rate(metric[k])}</td>' for k in ('precision_micro','recall_micro','f1_micro','precision_macro','recall_macro','f1_macro')) + '</tr>')
    counts = document['counts']
    if task_id is not None:
        selected = [r for r in document['rows'] if r['task_id'] == task_id]
        counts = {'target_count':len(selected), 'scored_count':sum(r['testcase'] is not None for r in selected),
                  'failed_target_count':sum(r['state'] in {'FAILED','BLOCKED'} for r in selected),
                  'unscorable_target_count':sum(r['testcase'] is None for r in selected),
                  'invalid_prediction_count':sum(len(r['prediction']['invalid']) for r in selected),
                  'no_positive_false_alarm_count':sum(r.get('false_alarm_count',0) for r in selected),
                  'statuses':{status:sum(r['status']==status for r in selected) for status in sorted({r['status'] for r in selected})}}
    return ('<section><h3>测试方法定位 · detect-metrics-v3</h3>'
            + f'<p>协议 {esc(document["protocol"])} · Targets {esc(counts["target_count"])} · 已计分 {esc(counts["scored_count"])} · 失败 {esc(counts.get("failed_target_count", 0))} · 不可评分 {esc(counts.get("unscorable_target_count", 0))} · 无效预测 {esc(counts.get("invalid_prediction_count", 0))} · 无正目标误报 {esc(counts.get("no_positive_false_alarm_count", 0))} · {esc(json.dumps(counts["statuses"], ensure_ascii=False))}</p>'
            + '<p>主指标为 testcase F1。失败在主指标中按零分计；历史不可评分和标签缺口明确列出。参数化按源码方法计数。</p>'
            + ('<div class="table-wrap"><table><thead><tr><th>方法</th><th>粒度</th><th>计分/全部</th><th>P micro</th><th>R micro</th><th>F1 micro</th><th>P macro</th><th>R macro</th><th>F1 macro</th></tr></thead><tbody>' + ''.join(summary) + '</tbody></table></div>' if summary else '')
            + details('双粒度明细', '<div class="table-wrap"><table><thead><tr><th>Task</th><th>方法</th><th>粒度</th><th>预测数</th><th>Gold 数</th><th>命中数</th><th>P</th><th>R</th><th>F1</th><th>状态</th></tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>', opened=task_id is not None)
            + '</section>')


def _batch_pr_detect_section(bench: Path, batch_id: str, task_id: str | None) -> str:
    """The Detect hit-rate table for one PR, or "" when nothing was recorded.

    Counts only, and deliberately so. The report behind this names gold files,
    while this page says in two places that gold data is excluded -- and
    ``write_report`` puts batch cards under ``batch/viewer-reports/``, which is
    not the gitignored ``Log/`` tree. A gold file name rendered here would be
    both a contradiction of the page's own claim and bytes that a single
    ``git add`` could commit. The file lists stay in the JSON.
    """
    document = detect_metrics(bench, batch_id)
    if document is None or task_id is None:
        return ""
    found = {
        row.get("method"): row
        for row in document["rows"]
        if isinstance(row, dict) and row.get("task_id") == task_id
    }
    if not found:
        return ""
    body: list[str] = []
    failures: list[str] = []
    for method in VARIANTS:
        row = found.get(method)
        if row is None:
            body.append(f"<tr><td>{esc(LABEL[method])}</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>")
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else None
        body.append(
            f'<tr><td>{esc(LABEL[method])}</td><td>{_detect_counts(row)}</td>'
            f'<td>{_rate(metrics.get("precision") if metrics else None)}</td>'
            f'<td>{_rate(metrics.get("recall") if metrics else None)}</td>'
            f'<td>{esc(row.get("status") or "UNKNOWN")}</td></tr>'
        )
        if row.get("status") == "ERROR":
            # A target that failed is shown, not omitted: a table that quietly
            # drops it reports a hit rate over the runs that happened to work.
            failures.append(
                f'<section class="failure"><h3>{esc(LABEL[method])}</h3>'
                f'<pre>{esc(row.get("error_code") or "ERROR")}: {esc(row.get("detail") or "")}</pre></section>'
            )
    return (
        "<section><h3>Detect 命中率</h3>"
        '<p class="source-path">a = 报出的 test 文件里 PR 真实改过的数量，b = 报出的 test 文件总数。'
        "命中率 = a/b；召回率 = a/gold 总数。两者都要看：只看命中率会奖励少报。</p>"
        '<div class="table-wrap"><table><thead><tr><th>Method</th><th>a / b</th>'
        "<th>命中率</th><th>召回率</th><th>Status</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
        + "".join(failures)
        + "</section>"
    )


def _batch_detect_table(bench: Path, batch_id: str) -> str:
    """The three-method comparison for the whole batch, or "" when unrecorded.

    The per-method figures are read straight out of the document rather than
    re-aggregated here: two implementations of one average is two answers to one
    question. ``a`` and ``b`` are shown as separate columns so a reader can check
    the rate in the next column against them.
    """
    document = detect_metrics(bench, batch_id)
    if document is None:
        return ""
    body: list[str] = []
    for record in document["methods"]:
        method = record.get("method") if isinstance(record, dict) else None
        if method not in LABEL:
            continue
        body.append(
            f'<tr><td>{esc(LABEL[method])}</td><td>{esc(record.get("row_count"))}</td>'
            f'<td>{esc(record.get("a"))}</td><td>{esc(record.get("b"))}</td>'
            f'<td>{_rate(record.get("hit_rate_micro"))}</td>'
            f'<td>{_rate(record.get("recall_micro"))}</td>'
            f'<td>{_rate(record.get("hit_rate_macro"))}</td></tr>'
        )
    if not body:
        return ""
    detail = []
    for row in document["rows"]:
        if not isinstance(row, dict):
            continue
        label = LABEL.get(row.get("method"), row.get("method"))
        record = f"{esc(label)} · {esc(row.get('run_id'))}"
        detail.append(
            f'<tr><td>{esc(row.get("task_id"))}</td><td>{record}</td>'
            f'<td>{_detect_counts(row)}</td>'
            f'<td>{_rate(row["metrics"].get("precision") if row.get("scorable") else None)}</td>'
            f'<td>{_rate(row["metrics"].get("recall") if row.get("scorable") else None)}</td>'
            f'<td>{esc(row.get("status") or "UNKNOWN")}</td></tr>'
        )
    counts = document.get("counts") if isinstance(document.get("counts"), dict) else {}
    source = f"Log/reports/detect-metrics/{batch_id}.json"
    return (
        "<section><h3>Detect 命中率（三方法对比）</h3>"
        '<p class="source-path">'
        f"Targets {esc(counts.get('target_count'))} · 出错 {esc(counts.get('error_count'))} · "
        f"无 gold {esc(counts.get('no_gold_count'))} · 非法候选 {esc(counts.get('invalid_candidate_count'))}"
        "</p>"
        '<div class="table-wrap"><table><thead><tr><th>Method</th><th>Targets</th><th>a</th><th>b</th>'
        "<th>命中率 (micro)</th><th>召回率 (micro)</th><th>宏平均命中率</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
        + details(
            "逐条明细",
            '<div class="table-wrap"><table><thead><tr><th>Task</th><th>Run</th><th>a / b</th>'
            "<th>命中率</th><th>召回率</th><th>Status</th></tr></thead><tbody>"
            + "".join(detail)
            + "</tbody></table></div>",
        )
        + f'<p class="source-path">来源 <code>{esc(source)}</code> · '
        f"重新生成 <code>./bin/sdd-detect-metrics check --batch {esc(batch_id)}</code></p>"
        "</section>"
    )


def _page_shell(title: str, tabs: str, nav: str, panes: str) -> str:
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (PAGE.replace("__TITLE__", esc(title))
        .replace("__VERSION__", VERSION)
        .replace("__TABS__", tabs)
        .replace("__NAV__", nav)
        .replace("__PANES__", panes)
        .replace("__GENERATED__", esc(generated)))


def build_batch_pr_html(exp: Experiment, bench: Path) -> str:
    return _layout().pr_page(sys.modules[__name__], bench, exp)


def build_batch_html(exp: Experiment, bench: Path) -> str:
    return _layout().batch_page(sys.modules[__name__], bench, exp)


def build_html(exp: Experiment, bench: Path | None = None) -> str:
    bench = bench or bench_default()
    if exp.source_kind == "batch":
        return build_batch_pr_html(exp, bench) if exp.task_id_filter else build_batch_html(exp, bench)
    available = [name for name in VARIANTS if (exp.root / name).is_dir()]
    panes = {"overview": render_overview(exp, available) + _usage_table(_legacy_token_usage(exp))}
    navigation: dict[str, list[tuple[str, str]]] = {"overview": []}
    for name in available:
        panes[name], navigation[name] = render_variant(name, exp.root / name)

    reference = dataset_reference(exp, bench)
    if reference:
        panes["reference"] = render_reference(reference)
        navigation["reference"] = []
    compare = comparison_sources(exp, reference)
    if len(compare) >= 2:
        panes["compare"] = render_comparison(compare)
        navigation["compare"] = []

    tab_labels = {"overview": "Overview", **LABEL, "reference": "PR & Gold", "compare": "Compare"}
    tabs = []
    for name in panes:
        active = " active" if name == "overview" else ""
        tabs.append(f'<button class="tab-button{active}" data-tab="{name}">{esc(tab_labels[name])}</button>')
    pane_html = "".join(
        f'<main class="tab-pane{" active" if name == "overview" else ""}" id="tab-{name}">{value}</main>'
        for name, value in panes.items()
    )
    nav_html = []
    for name, links in navigation.items():
        if links:
            nav_html.append(f'<div class="nav-group" data-nav="{name}"><h3>{esc(tab_labels.get(name, name))} files</h3>' + "".join(
                f'<a href="#{esc(anchor)}">{esc(label)}</a>' for label, anchor in links
            ) + "</div>")
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (PAGE.replace("__TITLE__", esc(exp.experiment_id))
        .replace("__VERSION__", VERSION)
        .replace("__TABS__", "".join(tabs))
        .replace("__NAV__", "".join(nav_html) or '<p class="source-path">No captured files.</p>')
        .replace("__PANES__", pane_html)
        .replace("__GENERATED__", esc(generated)))


def write_report(bench: Path, exp: Experiment, output: Path | None) -> Path:
    default_root = bench / "batch" / "viewer-reports" if exp.source_kind == "batch" else bench / "Log" / "reports"
    destination = (output or default_root / f"{slug(exp.experiment_id)}.html").expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + f".tmp-{os.getpid()}")
    temporary.write_text(build_html(exp, bench), encoding="utf-8")
    temporary.replace(destination)
    return destination



def _layout():
    if str(bench_default()) not in sys.path:
        sys.path.insert(0, str(bench_default()))
    from batch import results_ui
    return results_ui


def dashboard_html(experiments: list[Experiment], bench: Path | None = None) -> str:
    return _layout().homepage(sys.modules[__name__], bench or bench_default(), experiments)


def make_server(bench: Path, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"SDDResults/{VERSION}"

        def send_page(self, content: str, status: int = 200) -> None:
            payload = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            # JSON plus a custom header prevents cross-site form submissions.
            # Origin/Host are checked against the actual listener, including
            # forwarded localhost addresses used by SSH/IDE port forwarding.
            host_header = self.headers.get('Host', '')
            parsed_host = urlparse('http://' + host_header)
            origin = self.headers.get('Origin')
            bound_host, bound_port = self.server.server_address[:2]
            allowed_hosts = {'localhost', '127.0.0.1', '::1', bound_host}
            try:
                valid_host = parsed_host.hostname in allowed_hosts and (parsed_host.port or 80) == bound_port
            except ValueError:
                valid_host = False
            if (urlparse(self.path).path != '/api/note' or not valid_host
                    or self.headers.get('X-SDD-Viewer') != 'notes-v1'
                    or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
                    or (origin is not None and origin != 'http://' + host_header)):
                self.send_json({'error': '禁止此备注请求'}, 403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536:
                    raise ValueError('请求大小无效')
                value = json.loads(self.rfile.read(size))
                if not isinstance(value, dict):
                    raise ValueError('请求格式错误')
                _layout().save_note(bench, value.get('round_id'), value.get('batch_id'), value.get('text'), value.get('expected'))
            except (ValueError, OSError) as error:
                self.send_json({'error': str(error)}, 409)
                return
            self.send_json({'saved': True})

        def send_json(self, value: dict, status: int = 200) -> None:
            payload = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            try:
                self.get_page()
            except (ValueError, OSError, ViewerError) as error:
                self.send_page('<!doctype html><title>无法读取</title><h1>无法读取结果</h1><p>' + esc(str(error)) + '</p><a href="/">返回首页</a>', 422)

        def get_page(self) -> None:
            request_path = urlparse(self.path).path
            content_request = request_path.startswith('/content/')
            if content_request:
                request_path = request_path[len('/content'):]
            if request_path == "/healthz":
                payload = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if request_path.startswith('/api/intention-results/'):
                from batch import intention_results
                identifier = request_path[len('/api/intention-results/'):]
                entry = next((e for e in _layout().registry(bench)
                              if e['id'] == identifier and e.get('provider') == intention_results.PROVIDER), None)
                if entry is None:
                    self.send_json({'error': 'TI 轮次未登记'}, 404)
                else:
                    try:
                        self.send_json(intention_results.snapshot(bench, entry))
                    except (ValueError, OSError) as error:
                        self.send_json({'error': str(error)}, 422)
                return
            if request_path.startswith('/api/production-results/'):
                from batch import production_results
                identifier = request_path[len('/api/production-results/'):]
                entry = next((e for e in _layout().registry(bench)
                              if e['id'] == identifier and e.get('provider') == production_results.PROVIDER), None)
                if entry is None:
                    self.send_json({'error': '两阶段轮次未登记'}, 404)
                else:
                    self.send_json(production_results.snapshot(bench, entry))
                return
            current = discover(bench)
            slow_page = (request_path.startswith(('/round/', '/experiment/', '/attempt/', '/production-pr/'))
                         or (request_path == '/compare' and bool(urlparse(self.path).query)))
            if slow_page and not content_request:
                destination = '/content' + request_path
                if urlparse(self.path).query:
                    destination += '?' + urlparse(self.path).query
                self.send_page(_layout().loading_page(sys.modules[__name__], destination))
                return
            if request_path == "/":
                self.send_page(dashboard_html(current, bench))
                return
            if request_path == '/history':
                self.send_page(_layout().homepage(sys.modules[__name__], bench, current, history=True))
                return
            if request_path.startswith('/round/'):
                self.send_page(_layout().round_page(sys.modules[__name__], bench, current, request_path[len('/round/'):]))
                return
            if request_path.startswith('/production-pr/'):
                from batch import production_results
                parts = request_path.split('/')
                entry = next((e for e in _layout().registry(bench) if len(parts) == 4 and e['id'] == parts[2]
                              and e.get('provider') == production_results.PROVIDER), None)
                if entry is not None and parts[3].isdigit():
                    self.send_page(production_results.pr_page(sys.modules[__name__], _layout(), bench, entry, int(parts[3])))
                    return
            if request_path == '/compare':
                selected = parse_qs(urlparse(self.path).query).get('round', [])
                self.send_page(_layout().compare_page(sys.modules[__name__], bench, current, selected))
                return
            if request_path.startswith('/attempt/'):
                parts = request_path.split('/')
                if len(parts) == 4:
                    matches = [e for e in current if e.source_kind == 'batch' and experiment_token(e) == parts[2]]
                    if len(matches) == 1:
                        self.send_page(_layout().attempt_page(sys.modules[__name__], bench, matches[0], parts[3]))
                        return
            prefix = "/experiment/"
            if request_path.startswith(prefix):
                token = request_path[len(prefix):]
                matches = [item for item in current if experiment_token(item) == token]
                if len(matches) == 1:
                    page = build_html(matches[0], bench).replace(
                        '<div class="brand">',
                        '<div class="brand"><a href="/" style="color:#9eabc2;text-decoration:none;margin-right:14px">← Experiments</a>',
                        1,
                    )
                    self.send_page(page)
                    return
            self.send_page("<!doctype html><title>Not found</title><h1>404 · Experiment not found</h1><p><a href='/'>Return to dashboard</a></p>", 404)

        def log_message(self, message: str, *args: object) -> None:
            print(f"viewer_request={self.address_string()} {message % args}", file=sys.stderr)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def serve(bench: Path, host: str, port: int, open_browser: bool) -> int:
    try:
        server = make_server(bench, host, port)
    except OSError as error:
        raise ViewerError(f"cannot listen on {host}:{port}: {error}") from error
    actual_host, actual_port = server.server_address[:2]
    browser_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    url = f"http://{browser_host}:{actual_port}/"
    print(f"SDD Results Dashboard v{VERSION}")
    print(f"URL: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nviewer_stopped=true")
    finally:
        server.server_close()
    return 0

def print_list(experiments: list[Experiment], bench: Path | None = None) -> None:
    if not experiments:
        print("No experiments found.")
        return
    bench = bench or bench_default()
    header = ("EXPERIMENT", "TYPE", "STATUS", "SDDS", "UPDATED", "TASK")
    rows = []
    for exp in experiments:
        present = ",".join(_batch_present(exp, bench)) or "—"
        kind = "batch/pr" if exp.task_id_filter else exp.source_kind
        rows.append((exp.experiment_id, kind, overall_status(exp, bench), present, stamp(exp.modified), task_id(exp) or "—"))
    widths = [max(len(header[index]), *(len(row[index]) for row in rows)) for index in range(len(header))]
    print("  ".join(header[index].ljust(widths[index]) for index in range(len(header))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(header))))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="sdd-results", description="Discover SDD experiments and build a self-contained HTML viewer.")
    result.add_argument("--bench-root", type=Path, default=bench_default(), help=argparse.SUPPRESS)
    result.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    commands = result.add_subparsers(dest="command")
    commands.add_parser("list", help="list every discovered experiment")
    serve_parser = commands.add_parser("serve", help="start the browser dashboard")
    serve_parser.add_argument("--host", default="127.0.0.1", help="listen address (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8765, help="listen port (default: 8765)")
    serve_parser.add_argument("--open", action="store_true", help="ask the host to open a browser")
    report = commands.add_parser("report", help="generate a standalone HTML report")
    report.add_argument("experiment", nargs="?", help="full or uniquely abbreviated experiment id")
    report.add_argument("--output", "-o", type=Path, help="custom HTML output path")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    bench = args.bench_root.expanduser().resolve()
    experiments = discover(bench)
    if args.command == "list":
        print_list(experiments, bench)
        return 0
    if args.command in {None, "serve"}:
        host = args.host if args.command == "serve" else "127.0.0.1"
        port = args.port if args.command == "serve" else 8765
        open_browser = args.open if args.command == "serve" else False
        return serve(bench, host, port, open_browser)
    if not experiments:
        raise ViewerError(f"no experiment results found beneath {bench / 'Log'} or {bench / 'batch/runs'}")
    selector = args.experiment if args.command == "report" else None
    exp = resolve(experiments, selector) if selector else choose(experiments, bench)
    output = args.output if args.command == "report" else None
    destination = write_report(bench, exp, output)
    print(f"experiment={exp.experiment_id}")
    print(f"status={overall_status(exp, bench)}")
    print(f"report={destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ViewerError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
