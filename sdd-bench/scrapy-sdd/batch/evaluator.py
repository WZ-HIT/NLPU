"""Host-only evaluation of sealed Detect and Update bundles.

The evaluator has a deliberate two-phase boundary: every configured Prompt 9
bundle is verified before the raw PR source is opened or gold is constructed.
No function in this module invokes an agent or appends to the batch ledger.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from .core import BatchError, canonical_sha256, sha256_file
from .orchestrator import Ledger, _latest, target_key, validate_batch_config
from .reporting import (
    Evidence,
    ReportingError,
    _attempt_path,
    _verify_barrier,
    _verify_detection,
    _verify_update,
)

EVALUATOR_VERSION = "prompt10-evaluator-v1"
METRIC_VERSION = "prompt10-metrics-v1"
ATTRIBUTION_PRECEDENCE = (
    "invalid_evidence",
    "infrastructure_failure",
    "policy_violation",
    "localization_miss",
    "update_selection_miss",
    "patch_application_failure",
    "functional_failure",
    "success",
)
TEST_PREFIXES = {"test", "tests", "testing"}
PYTEST_COUNTS = re.compile(
    r"(?P<count>[0-9]+) (?P<kind>passed|failed|error|errors|skipped|xfailed|xpassed)"
)


class EvaluationError(BatchError):
    """Structured host-evaluation failure."""


def _validate(value: dict[str, Any], schema: Path, code: str) -> None:
    validator = Draft202012Validator(
        json.loads(schema.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise EvaluationError(
            code,
            "JSON document failed schema validation",
            errors=[error.message for error in errors],
        )


def _self_hash(value: dict[str, Any], field: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if not isinstance(supplied, str) or supplied != canonical_sha256(payload):
        raise EvaluationError("EVALUATION_SELF_HASH_INVALID", "Document self-hash differs", field=field)


def _safe_path(value: str, *, tests_only: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "//" in value:
        raise EvaluationError("INVALID_TARGET_PATH", "Target path is not safe", path=value)
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise EvaluationError("INVALID_TARGET_PATH", "Target path is not repository-relative", path=value)
    normalized = pure.as_posix()
    if normalized.startswith("./") or normalized != value:
        raise EvaluationError("INVALID_TARGET_PATH", "Target path is not canonical", path=value)
    if tests_only and pure.parts[0] not in TEST_PREFIXES:
        raise EvaluationError("NON_TEST_TARGET", "Evaluation target is outside test roots", path=value)
    return normalized


def _repo_path(repository_root: Path, value: str) -> Path:
    normalized = _safe_path(value)
    result = repository_root.joinpath(*PurePosixPath(normalized).parts)
    try:
        result.resolve().relative_to(repository_root.resolve())
    except ValueError as exc:
        raise EvaluationError("EVALUATION_PATH_ESCAPE", "Evaluation path escapes repository", path=value) from exc
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EvaluationError("EVALUATION_INPUT_INVALID", "Expected a regular input file", path=str(path))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvaluationError("EVALUATION_INPUT_INVALID", "Expected a JSON object", path=str(path))
    return value


def _opaque_id(evaluation_id: str, kind: str, identity: str) -> str:
    digest = hashlib.sha256(f"{evaluation_id}\0{kind}\0{identity}".encode("utf-8")).hexdigest()
    return f"g-{digest[:24]}"


def _target_id(target: dict[str, Any]) -> str:
    return hashlib.sha256(target_key(target).encode("utf-8")).hexdigest()[:24]


def _patch_paths_in_order(text: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("+++ "):
            continue
        value = line[4:].split("\t", 1)[0]
        if value == "/dev/null":
            continue
        if value.startswith("b/"):
            value = value[2:]
        value = _safe_path(value, tests_only=True)
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _raw_patch(path: str, body: str) -> str:
    normalized = _safe_path(path)
    if not isinstance(body, str) or not body.startswith("@@"):
        raise EvaluationError("RAW_PATCH_INVALID", "Raw changed-file patch is missing or malformed", path=path)
    return f"diff --git a/{normalized} b/{normalized}\n--- a/{normalized}\n+++ b/{normalized}\n{body.rstrip()}\n"


def _copy_tree_writable(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, symlinks=True)
    for path in [destination, *destination.rglob("*")]:
        if path.is_symlink():
            continue
        try:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        except FileNotFoundError:
            pass


def _apply_patch(workspace: Path, patch: str) -> tuple[bool, str]:
    completed = subprocess.run(
        ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
        input=patch.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    detail = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    return completed.returncode == 0, detail


def _definitions(source: str, filename: str) -> list[dict[str, Any]]:
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines()
    values: list[dict[str, Any]] = []

    class Collector(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.scope.append(node.name)
            for child in node.body:
                self.visit(child)
            self.scope.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.record(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.record(node)

        def record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            name = ".".join([*self.scope, node.name])
            starts = [node.lineno, *(item.lineno for item in node.decorator_list)]
            start = min(starts)
            end = node.end_lineno or node.lineno
            fragment = "\n".join(lines[start - 1 : end])
            values.append(
                {
                    "path": filename,
                    "qualified_name": name,
                    "name": node.name,
                    "start_line": start,
                    "end_line": end,
                    "sha256": hashlib.sha256(fragment.encode("utf-8")).hexdigest(),
                }
            )
            self.scope.append(node.name)
            for child in node.body:
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.visit(child)
            self.scope.pop()

    Collector().visit(tree)
    return values


def _changed_symbols(base: Path, candidate: Path, paths: Sequence[str]) -> tuple[list[dict[str, str]], list[str]]:
    result: list[dict[str, str]] = []
    invalid: list[str] = []
    for value in paths:
        before_path = base / value
        after_path = candidate / value
        try:
            before = _definitions(before_path.read_text(encoding="utf-8"), value) if before_path.is_file() else []
            after = _definitions(after_path.read_text(encoding="utf-8"), value) if after_path.is_file() else []
        except (OSError, UnicodeError, SyntaxError) as exc:
            invalid.append(f"{value}:{type(exc).__name__}")
            continue
        before_by_name = {item["qualified_name"]: item for item in before}
        after_by_name = {item["qualified_name"]: item for item in after}
        changed = []
        for name in before_by_name.keys() | after_by_name.keys():
            old = before_by_name.get(name)
            new = after_by_name.get(name)
            if old is None or new is None or old["sha256"] != new["sha256"]:
                representative = new or old
                assert representative is not None
                changed.append(representative)
        changed.sort(key=lambda item: (item["start_line"], item["qualified_name"]))
        result.extend({"path": value, "qualified_name": item["qualified_name"]} for item in changed)
    return result, invalid


def _resolve_detect_symbols(
    baseline: Path, candidates: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, str]], list[str]]:
    result: list[dict[str, str]] = []
    invalid: list[str] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        try:
            path = _safe_path(candidate.get("path"), tests_only=True)
        except EvaluationError:
            invalid.append("invalid-path")
            continue
        try:
            definitions = _definitions((baseline / path).read_text(encoding="utf-8"), path)
        except (OSError, UnicodeError, SyntaxError):
            definitions = []
        by_qualified = {item["qualified_name"]: item for item in definitions}
        by_leaf: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in definitions:
            by_leaf[item["name"]].append(item)
        symbols = candidate.get("symbols", [])
        if not isinstance(symbols, list):
            invalid.append(f"{path}:symbols-not-array")
            continue
        for supplied in symbols:
            if not isinstance(supplied, str) or not supplied:
                invalid.append(f"{path}:invalid-symbol")
                continue
            match = by_qualified.get(supplied)
            if match is None and len(by_leaf.get(supplied, [])) == 1:
                match = by_leaf[supplied][0]
            if match is None:
                invalid.append(f"{path}:{supplied}:unresolved")
                continue
            qualified = match["qualified_name"]
            identity = (path, qualified)
            if identity in seen:
                invalid.append(f"{path}:{supplied}:duplicate")
                continue
            seen.add(identity)
            result.append({"path": path, "qualified_name": qualified})
    return result, invalid


def _identity(value: str | dict[str, str]) -> str:
    if isinstance(value, str):
        return value
    return f"{value['path']}::{value['qualified_name']}"


def score_ranked(
    predicted: Sequence[str | dict[str, str]],
    gold: Sequence[str | dict[str, str]],
    *,
    cutoffs: Sequence[int] = (1, 3, 5),
    invalid_count: int = 0,
    missing_count: int = 0,
) -> dict[str, Any]:
    """Return deterministic set and ranking metrics with explicit accounting."""
    predicted_ids = [_identity(item) for item in predicted]
    gold_ids = [_identity(item) for item in gold]
    predicted_set = set(predicted_ids)
    gold_set = set(gold_ids)
    matched = predicted_set & gold_set
    tp = len(matched)
    fp = len(predicted_set - gold_set)
    fn = len(gold_set - predicted_set)
    precision = tp / len(predicted_set) if predicted_set else 0.0
    recall = tp / len(gold_set) if gold_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    first = next((index for index, item in enumerate(predicted_ids, 1) if item in gold_set), None)
    ranking = {}
    for cutoff in cutoffs:
        prefix = set(predicted_ids[:cutoff])
        hits = len(prefix & gold_set)
        ranking[f"hit_at_{cutoff}"] = int(hits > 0)
        ranking[f"recall_at_{cutoff}"] = hits / len(gold_set) if gold_set else 0.0
    return {
        "metric_definition_version": METRIC_VERSION,
        "gold_count": len(gold_set),
        "predicted_count": len(predicted_set),
        "matched_count": tp,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "exact_match": int(predicted_set == gold_set),
        "any_hit": int(tp > 0),
        "all_hit": int(gold_set.issubset(predicted_set)),
        **ranking,
        "mrr": 1.0 / first if first else 0.0,
        "gold_to_predicted_ratio": len(gold_set) / len(predicted_set) if predicted_set else None,
        "invalid_count": invalid_count,
        "missing_count": missing_count,
        "scorable_count": len(gold_set),
    }


def choose_attribution(flags: dict[str, bool]) -> str:
    """Select one mutually exclusive attribution by documented precedence."""
    mapping = {
        "invalid_evidence": "invalid_evidence",
        "infrastructure_failure": "infrastructure_failure",
        "policy_violation": "policy_violation",
        "localization_miss": "localization_miss",
        "update_selection_miss": "update_selection_miss",
        "patch_application_failure": "patch_application_failure",
        "functional_failure": "functional_failure",
    }
    for name in ATTRIBUTION_PRECEDENCE:
        if name == "success":
            return name
        if flags.get(mapping[name], False):
            return name
    return "success"


def _public_targets(
    evaluation_id: str,
    kind: str,
    predicted: Sequence[str | dict[str, str]],
    gold: Sequence[str | dict[str, str]],
    invalid: Sequence[str],
) -> dict[str, Any]:
    gold_by_identity = {
        _identity(item): _opaque_id(evaluation_id, kind, _identity(item)) for item in gold
    }
    rows = []
    matched_ids: list[str] = []
    for rank, item in enumerate(predicted, 1):
        identity = _identity(item)
        row: dict[str, Any] = {"rank": rank, "candidate": item}
        if identity in gold_by_identity:
            row["matched_gold_id"] = gold_by_identity[identity]
            matched_ids.append(gold_by_identity[identity])
        rows.append(row)
    return {
        "predicted": rows,
        "gold_ids": sorted(gold_by_identity.values()),
        "matched_gold_ids": sorted(set(matched_ids)),
        "invalid_evidence_ids": [
            hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] for value in invalid
        ],
        "invalid_count": len(invalid),
        "missing_count": len(set(gold_by_identity) - {_identity(item) for item in predicted}),
    }


def _load_plan(plan_path: Path, bench: Path, repository_root: Path) -> dict[str, Any]:
    plan = _read_json(plan_path)
    _validate(plan, bench / "schemas/host-evaluation-plan-v1.schema.json", "EVALUATION_PLAN_INVALID")
    if plan.get("evaluator_version") != EVALUATOR_VERSION or plan.get("metric_definition_version") != METRIC_VERSION:
        raise EvaluationError("EVALUATION_VERSION_MISMATCH", "Evaluation plan pins another implementation")
    for field in ("batch_config", "raw_source"):
        artifact = plan[field]
        path = _repo_path(repository_root, artifact["path"])
        if path.is_symlink() or not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise EvaluationError("EVALUATION_PLAN_ARTIFACT_MISMATCH", "Pinned evaluation input changed", field=field)
    return plan


def _verify_sealed_batch(
    *, config_path: Path, bench: Path, repository_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, Any], str]:
    """Verify all sealed outputs. This must complete before any gold read."""
    config, targets = validate_batch_config(config_path, bench, repository_root)
    detect_targets = [item for item in targets if item["stage"] == "detect"]
    update_targets = [item for item in targets if item["stage"] == "update"]
    if len(targets) != 27 or len(detect_targets) != 9 or len(update_targets) != 18:
        raise EvaluationError("TARGET_UNIVERSE_INVALID", "Host evaluation requires exactly 9 Detect and 18 Update targets")
    run_root = bench / "batch/runs" / config["batch_id"]
    ledger_path = run_root / "ledger.jsonl"
    ledger_sha = sha256_file(ledger_path)
    ledger = Ledger(ledger_path, config["batch_id"], bench / "schemas/batch-ledger-event-v1.schema.json")
    latest = _latest(ledger.read())
    for target in targets:
        expected = "DETECT_SEALED" if target["stage"] == "detect" else "UPDATE_SEALED"
        event = latest.get(target_key(target))
        if event is None or event.get("state") != expected:
            raise EvaluationError("TARGET_NOT_SEALED", "Configured target is not sealed", target=target_key(target))
    evidence = Evidence(repository_root)
    barrier = _verify_barrier(config, detect_targets, run_root, repository_root, evidence)
    manifests: dict[tuple[str, str], dict[str, Any]] = {}
    for target in sorted(detect_targets, key=target_key):
        _, manifest, _ = _verify_detection(
            target, latest[target_key(target)], bench, repository_root, evidence
        )
        manifests[(target["task_id"], target["method"])] = manifest
    for target in sorted(update_targets, key=target_key):
        _verify_update(
            target,
            latest[target_key(target)],
            manifests[(target["task_id"], target["method"])],
            bench,
            repository_root,
            evidence,
        )
    if sha256_file(ledger_path) != ledger_sha:
        raise EvaluationError("LEDGER_MUTATED", "Ledger changed during seal verification")
    return config, targets, latest, manifests, barrier, ledger_sha


def _raw_records(path: Path, task_manifests: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    wanted = {
        (f"{task['repository']['owner']}/{task['repository']['name']}", task["pr_id"]): task["task_id"]
        for task in task_manifests
    }
    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        key = (value.get("repo"), value.get("pr_id"))
        if key in wanted:
            matches[wanted[key]].append(value)
    if set(matches) != set(wanted.values()) or any(len(values) != 1 for values in matches.values()):
        raise EvaluationError("RAW_GOLD_NOT_UNIQUE", "Expected exactly one raw record per configured task")
    return {task_id: values[0] for task_id, values in matches.items()}


def _construct_gold(
    *,
    plan: dict[str, Any],
    config: dict[str, Any],
    targets: list[dict[str, Any]],
    barrier: dict[str, Any],
    bench: Path,
    repository_root: Path,
) -> tuple[dict[str, Any], Path]:
    task_paths = {item["task_id"]: item["task_manifest"] for item in targets}
    task_documents = [_read_json(path) for _, path in sorted(task_paths.items())]
    plan_document = _read_json(_repo_path(repository_root, config["approved_plan"]["path"]))
    classifications = {item["task_id"]: item["classification"] for item in plan_document["tasks"]}
    raw_path = _repo_path(repository_root, plan["raw_source"]["path"])
    records = _raw_records(raw_path, task_documents)
    tasks = []
    for task in sorted(task_documents, key=lambda item: item["task_id"]):
        task_id = task["task_id"]
        raw = records[task_id]
        test_files: list[str] = []
        production_patches: list[dict[str, str]] = []
        test_patches: list[dict[str, str]] = []
        for changed in raw.get("changed_files", []):
            if not isinstance(changed, dict) or not isinstance(changed.get("filename"), str):
                continue
            path = _safe_path(changed["filename"])
            patch = _raw_patch(path, changed.get("patch"))
            entry = {"path": path, "patch": patch, "sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest()}
            if PurePosixPath(path).parts[0] in TEST_PREFIXES:
                test_files.append(path)
                test_patches.append(entry)
            else:
                production_patches.append(entry)
        test_files = list(dict.fromkeys(test_files))
        symbols: list[dict[str, str]] = []
        seen_symbols: set[tuple[str, str]] = set()
        for changed in raw.get("test_changes", []):
            if not isinstance(changed, dict):
                continue
            path = changed.get("file")
            qualified = changed.get("qualified_name") or changed.get("name")
            if not isinstance(path, str) or not isinstance(qualified, str) or not qualified:
                continue
            path = _safe_path(path, tests_only=True)
            identity = (path, qualified)
            if identity not in seen_symbols:
                symbols.append({"path": path, "qualified_name": qualified})
                seen_symbols.add(identity)
        if not test_files or not symbols:
            raise EvaluationError("GOLD_TARGETS_EMPTY", "Gold file or symbol targets are empty", task_id=task_id)
        if classifications[task_id] == "MIXED_CODE_AND_TEST_PR" and not production_patches:
            raise EvaluationError("MIXED_GOLD_PATCH_MISSING", "Mixed PR lacks a hidden production patch", task_id=task_id)
        tasks.append(
            {
                "task_id": task_id,
                "classification": classifications[task_id],
                "base_sha": task["baseline"]["base_sha"],
                "raw_record_sha256": canonical_sha256(raw),
                "test_files": [
                    {"id": _opaque_id(plan["evaluation_id"], "file", value), "path": value}
                    for value in test_files
                ],
                "test_symbols": [
                    {"id": _opaque_id(plan["evaluation_id"], "symbol", _identity(value)), **value}
                    for value in symbols
                ],
                "test_patches": test_patches,
                "production_patches": production_patches,
                "future_revision_commitments": {
                    "head_sha256": hashlib.sha256(str(raw.get("head_sha", "")).encode("utf-8")).hexdigest(),
                    "merge_sha256": hashlib.sha256(str(raw.get("merge_commit_sha", "")).encode("utf-8")).hexdigest(),
                },
            }
        )
    store = {
        "schema_version": 1,
        "store_type": "PROMPT10_HOST_ONLY_GOLD",
        "evaluation_id": plan["evaluation_id"],
        "batch_id": config["batch_id"],
        "metric_definition_version": METRIC_VERSION,
        "seal_barrier_sha256": barrier["barrier_sha256"],
        "raw_source_sha256": plan["raw_source"]["sha256"],
        "tasks": tasks,
    }
    store["gold_seal_sha256"] = canonical_sha256(store)
    _validate(store, bench / "schemas/host-gold-store-v1.schema.json", "GOLD_STORE_INVALID")
    gold_dir = bench / "batch/gold/prompt10" / plan["evaluation_id"]
    gold_path = gold_dir / "gold-store.json"
    payload = (json.dumps(store, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if gold_path.exists():
        if gold_path.is_symlink() or gold_path.read_bytes() != payload:
            raise EvaluationError("GOLD_STORE_MISMATCH", "Existing Prompt 10 gold differs")
    else:
        gold_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        gold_dir.chmod(0o700)
        temporary = gold_dir / ".gold-store.tmp"
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, gold_path)
    gold_path.chmod(0o600)
    return store, gold_path


def _gold_task(store: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [item for item in store["tasks"] if item["task_id"] == task_id]
    if len(matches) != 1:
        raise EvaluationError("GOLD_TASK_INVALID", "Gold task is absent or duplicated", task_id=task_id)
    return matches[0]


def _baseline(bench: Path, base_sha: str) -> Path:
    path = bench / "batch/baselines" / base_sha / "repository"
    if path.is_symlink() or not path.is_dir():
        raise EvaluationError("BASELINE_MISSING", "Pinned pure baseline is absent", base_sha=base_sha)
    return path


def _resource_profile(bench: Path, base_sha: str, plan: dict[str, Any]) -> tuple[str, str]:
    lock_path = bench / "batch/images" / base_sha / "deployment-lock.json"
    lock = _read_json(lock_path)
    image = lock.get("images", {}).get("baseline", {})
    tag = image.get("tag")
    if not isinstance(tag, str) or not tag:
        raise EvaluationError("EVALUATION_IMAGE_INVALID", "Baseline image tag is absent", base_sha=base_sha)
    profile = {
        "base_sha": base_sha,
        "image_id": image.get("image_id"),
        "python": lock.get("versions", {}).get("python"),
        "pytest": lock.get("versions", {}).get("pytest"),
        "behavior": plan["behavior"],
    }
    return tag, canonical_sha256(profile)


def _sanitize_log(text: str, workspace: Path, sentinels: Iterable[str]) -> str:
    clean = text.replace(str(workspace), "<WORKSPACE>")
    clean = re.sub(r"/tmp/sdd-eval-[^/\s]+", "<WORKSPACE>", clean)
    for sentinel in sentinels:
        if sentinel and len(sentinel) >= 16 and sentinel in clean:
            clean = clean.replace(sentinel, "<REDACTED>")
    return clean[-200000:]


def _pytest_counts(text: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for match in PYTEST_COUNTS.finditer(text):
        kind = match.group("kind")
        if kind == "error":
            kind = "errors"
        if kind in counts:
            counts[kind] = int(match.group("count"))
    return counts


def _outcome(exit_code: int | None, timed_out: bool, counts: dict[str, int], text: str) -> str:
    if timed_out:
        return "TIMEOUT"
    if exit_code == 0:
        return "PASS"
    if exit_code == 5 or "no tests ran" in text.lower() or "collected 0 items" in text.lower():
        return "COLLECTION_FAILURE"
    if exit_code == 1 or counts["failed"] or counts["errors"]:
        return "FAIL"
    return "ERROR"


def _run_pytest(
    *,
    workspace: Path,
    image: str,
    paths: Sequence[str],
    plan: dict[str, Any],
    sentinels: Iterable[str],
) -> tuple[dict[str, Any], str]:
    argv = [*plan["behavior"]["pytest_argv"], *paths]
    docker = [
        "docker", "run", "--rm", "--network", plan["behavior"]["network"],
        "--cpus", plan["behavior"]["cpus"], "--memory", plan["behavior"]["memory"],
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777", "--mount",
        f"type=bind,src={workspace},dst=/workspace", "--workdir", "/workspace",
        "--env", "PYTHONDONTWRITEBYTECODE=1", image, *argv,
    ]
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            docker,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=plan["behavior"]["timeout_seconds"],
            check=False,
        )
        exit_code: int | None = completed.returncode
        raw = completed.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        raw = (exc.stdout or b"").decode("utf-8", errors="replace")
    duration_ms = int((time.monotonic() - started) * 1000)
    clean = _sanitize_log(raw, workspace, sentinels)
    counts = _pytest_counts(clean)
    result = {
        "outcome": _outcome(exit_code, timed_out, counts, clean),
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "counts": counts,
        "command_sha256": canonical_sha256(argv),
        "log_sha256": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
    }
    return result, clean


def _behavior_transition(classification: str, runs: Sequence[dict[str, Any]]) -> str:
    if any(item["outcome"] in {"ERROR", "TIMEOUT", "COLLECTION_FAILURE"} for item in runs):
        return "INVALID"
    if classification == "TEST_ONLY_PR":
        return "PASSING" if runs[0]["outcome"] == "PASS" else "FAILING"
    by_environment = {item["environment"]: item["outcome"] for item in runs}
    base = by_environment.get("PURE_BASE")
    oracle = by_environment.get("HIDDEN_PRODUCTION_PATCH")
    if base == "FAIL" and oracle == "PASS":
        return "DISCRIMINATING"
    if base == "PASS" and oracle == "PASS":
        return "NON_DISCRIMINATING"
    if base == "FAIL" and oracle == "FAIL":
        return "INEFFECTIVE"
    if base == "PASS" and oracle == "FAIL":
        return "REGRESSIVE"
    return "INVALID"


def _evaluate_behavior(
    *,
    target: dict[str, Any],
    patch: str,
    patch_paths: Sequence[str],
    gold: dict[str, Any],
    bench: Path,
    plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    image, resource_sha = _resource_profile(bench, gold["base_sha"], plan)
    baseline = _baseline(bench, gold["base_sha"])
    environments = ["PURE_BASE"]
    if gold["classification"] == "MIXED_CODE_AND_TEST_PR":
        environments.append("HIDDEN_PRODUCTION_PATCH")
    hidden = "".join(item["patch"] for item in gold["production_patches"])
    sentinels = [item["patch"] for item in gold["production_patches"]]
    runs: list[dict[str, Any]] = []
    logs: dict[str, str] = {}
    patch_application_ok = True
    with tempfile.TemporaryDirectory(prefix="sdd-eval-") as temporary:
        root = Path(temporary)
        for environment in environments:
            workspace = root / environment.lower()
            _copy_tree_writable(baseline, workspace)
            if environment == "HIDDEN_PRODUCTION_PATCH":
                ok, detail = _apply_patch(workspace, hidden)
                if not ok:
                    patch_application_ok = False
                    clean = _sanitize_log(detail, workspace, sentinels)
                    logs[environment] = clean
                    runs.append(
                        {
                            "environment": environment,
                            "outcome": "ERROR",
                            "exit_code": None,
                            "duration_ms": 0,
                            "counts": {"passed": 0, "failed": 0, "errors": 1, "skipped": 0},
                            "command_sha256": canonical_sha256(plan["behavior"]["pytest_argv"]),
                            "log_sha256": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                        }
                    )
                    continue
            ok, detail = _apply_patch(workspace, patch)
            if not ok:
                patch_application_ok = False
                clean = _sanitize_log(detail, workspace, sentinels)
                logs[environment] = clean
                runs.append(
                    {
                        "environment": environment,
                        "outcome": "ERROR",
                        "exit_code": None,
                        "duration_ms": 0,
                        "counts": {"passed": 0, "failed": 0, "errors": 1, "skipped": 0},
                        "command_sha256": canonical_sha256(plan["behavior"]["pytest_argv"]),
                        "log_sha256": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                    }
                )
                continue
            result, clean = _run_pytest(
                workspace=workspace,
                image=image,
                paths=patch_paths,
                plan=plan,
                sentinels=sentinels,
            )
            result["environment"] = environment
            runs.append(result)
            logs[environment] = clean
    behavior = {
        "schema_version": 1,
        "artifact_type": "HOST_BEHAVIOR_RESULT",
        "evaluation_id": plan["evaluation_id"],
        "target_id": _target_id(target),
        "classification": gold["classification"],
        "patch_application_ok": patch_application_ok,
        "workspace_purity": {
            "fresh_from_pinned_base": True,
            "candidate_patch_only": True,
            "gold_tests_injected": False,
            "network": "none",
            "cleaned": True,
        },
        "resource_profile_sha256": resource_sha,
        "runs": runs,
        "transition": _behavior_transition(gold["classification"], runs),
    }
    behavior["behavior_sha256"] = canonical_sha256(behavior)
    return behavior, logs


def _target_sets_and_metrics(
    *,
    target: dict[str, Any],
    manifest: dict[str, Any] | None,
    patch: str | None,
    baseline: Path,
    gold: dict[str, Any],
    plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    gold_files = [item["path"] for item in gold["test_files"]]
    gold_symbols = [
        {"path": item["path"], "qualified_name": item["qualified_name"]}
        for item in gold["test_symbols"]
    ]
    file_invalid: list[str] = []
    symbol_invalid: list[str] = []
    if target["stage"] == "detect":
        assert manifest is not None
        predicted_files = []
        seen_files: set[str] = set()
        candidates = manifest.get("candidates", [])
        for item in candidates:
            try:
                path = _safe_path(item.get("path"), tests_only=True)
            except EvaluationError:
                file_invalid.append("invalid-path")
                continue
            if path in seen_files:
                file_invalid.append(f"{path}:duplicate")
                continue
            predicted_files.append(path)
            seen_files.add(path)
        predicted_symbols, symbol_invalid = _resolve_detect_symbols(baseline, candidates)
        patch_paths: list[str] = []
    else:
        assert patch is not None
        try:
            predicted_files = _patch_paths_in_order(patch)
        except EvaluationError as exc:
            predicted_files = []
            file_invalid.append(exc.code)
        patch_paths = list(predicted_files)
        with tempfile.TemporaryDirectory(prefix="sdd-targets-") as temporary:
            candidate = Path(temporary) / "candidate"
            _copy_tree_writable(baseline, candidate)
            applied, _ = _apply_patch(candidate, patch)
            if applied:
                predicted_symbols, symbol_invalid = _changed_symbols(
                    baseline, candidate, predicted_files
                )
            else:
                predicted_symbols = []
                symbol_invalid = ["candidate-patch-application-failed"]
    file_metrics = score_ranked(
        predicted_files,
        gold_files,
        cutoffs=plan["ranking_cutoffs"],
        invalid_count=len(file_invalid),
        missing_count=len(set(gold_files) - set(predicted_files)),
    )
    symbol_metrics = score_ranked(
        predicted_symbols,
        gold_symbols,
        cutoffs=plan["ranking_cutoffs"],
        invalid_count=len(symbol_invalid),
        missing_count=len({_identity(item) for item in gold_symbols} - {_identity(item) for item in predicted_symbols}),
    )
    target_set = {
        "schema_version": 1,
        "artifact_type": "PUBLIC_TARGET_SET",
        "evaluation_id": plan["evaluation_id"],
        "target_id": _target_id(target),
        "stage": target["stage"],
        "task_id": target["task_id"],
        "classification": gold["classification"],
        "method": target["method"],
        "update_mode": target["mode"],
        "metric_definition_version": METRIC_VERSION,
        "gold_seal_sha256": None,
        "files": _public_targets(plan["evaluation_id"], "file", predicted_files, gold_files, file_invalid),
        "symbols": _public_targets(plan["evaluation_id"], "symbol", predicted_symbols, gold_symbols, symbol_invalid),
    }
    return target_set, {"file": file_metrics, "symbol": symbol_metrics}, patch_paths, [*file_invalid, *symbol_invalid]


def _metric_summary(rows: Sequence[dict[str, Any]], level: str) -> dict[str, Any]:
    valid = [row for row in rows if row["validity"]["status"] == "VALID"]
    invalid = len(rows) - len(valid)
    metrics = [row["model_performance"][level] for row in valid]
    tp = sum(item["tp"] for item in metrics)
    fp = sum(item["fp"] for item in metrics)
    fn = sum(item["fn"] for item in metrics)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    micro_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    names = ("precision", "recall", "f1", "exact_match", "any_hit", "all_hit", "hit_at_1", "hit_at_3", "hit_at_5", "recall_at_1", "recall_at_3", "recall_at_5", "mrr")
    macro = {name: sum(item[name] for item in metrics) / len(metrics) if metrics else None for name in names}
    return {
        "metric_definition_version": METRIC_VERSION,
        "run_count": len(rows),
        "scorable_count": len(valid),
        "invalid_count": invalid + sum(item["invalid_count"] for item in metrics),
        "missing_count": sum(item["missing_count"] for item in metrics),
        "macro": macro,
        "micro": {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": micro_f1},
    }


def aggregate_rows(rows: Sequence[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    """Build required classification/method/mode aggregate slices."""
    stage_rows = [row for row in rows if row["stage"] == stage]
    specs: list[tuple[str, ...]] = [(), ("method",)]
    if stage == "update":
        specs.extend((("update_mode",), ("method", "update_mode")))
    output: list[dict[str, Any]] = []
    classifications = ("TEST_ONLY_PR", "MIXED_CODE_AND_TEST_PR", "ALL")
    for classification in classifications:
        scope = stage_rows if classification == "ALL" else [row for row in stage_rows if row["classification"] == classification]
        for dimensions in specs:
            groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
            for row in scope:
                groups[tuple(row[name] for name in dimensions)].append(row)
            if not dimensions and not groups:
                groups[tuple()] = []
            for key, members in sorted(groups.items(), key=lambda item: str(item[0])):
                output.append(
                    {
                        "classification": classification,
                        "dimensions": dict(zip(dimensions, key)),
                        "file": _metric_summary(members, "file"),
                        "symbol": _metric_summary(members, "symbol"),
                    }
                )
    return output


def _paired(evaluations: Sequence[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    updates = [item for item in evaluations if item["stage"] == "update"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in updates:
        groups[(item["task_id"], item["method"])].append(item)
    pairs = []
    wins = ties = losses = 0
    for (task_id, method), members in sorted(groups.items()):
        by_mode = {item["update_mode"]: item for item in members}
        reasons = []
        if set(by_mode) != {"sealed-detect", "self-directed"}:
            reasons.append("mode-member-missing")
        required = plan["pairing"]["required_equal"]
        if not reasons:
            left, right = by_mode["sealed-detect"], by_mode["self-directed"]
            values = {
                "task_id": lambda row: row["task_id"],
                "classification": lambda row: row["classification"],
                "method": lambda row: row["method"],
                "base_sha": lambda row: row["provenance"]["base_sha"],
                "resource_profile_sha256": lambda row: row["execution"]["resource_profile_sha256"],
                "gold_seal_sha256": lambda row: row["provenance"]["gold_seal_sha256"],
                "metric_definition_version": lambda row: row["metric_definition_version"],
                "validity": lambda row: row["validity"]["status"],
            }
            for name in required:
                if values[name](left) != values[name](right):
                    reasons.append(f"{name}-mismatch")
            if left["validity"]["status"] != "VALID":
                reasons.append("invalid-run")
        eligible = not reasons
        delta = None
        outcome = None
        if eligible:
            delta = (
                by_mode["sealed-detect"]["model_performance"]["file"]["f1"]
                - by_mode["self-directed"]["model_performance"]["file"]["f1"]
            )
            if delta > 0:
                outcome = "SEALED_DETECT_WIN"
                wins += 1
            elif delta < 0:
                outcome = "SELF_DIRECTED_WIN"
                losses += 1
            else:
                outcome = "TIE"
                ties += 1
        pairs.append(
            {
                "task_id": task_id,
                "method": method,
                "eligible": eligible,
                "exclusion_reasons": sorted(set(reasons)),
                "file_f1_delta_sealed_minus_self": delta,
                "outcome": outcome,
            }
        )
    return {
        "schema_version": 1,
        "artifact_type": "PAIRED_COMPARISONS",
        "evaluation_id": plan["evaluation_id"],
        "metric_definition_version": METRIC_VERSION,
        "eligible_pair_count": sum(item["eligible"] for item in pairs),
        "excluded_pair_count": sum(not item["eligible"] for item in pairs),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "inferential_significance_claimed": False,
        "pairs": pairs,
    }


def _policy_matrix(evaluations: Sequence[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    updates = [item for item in evaluations if item["stage"] == "update"]
    rows = []
    for classification in ("TEST_ONLY_PR", "MIXED_CODE_AND_TEST_PR", "ALL"):
        scope = updates if classification == "ALL" else [item for item in updates if item["classification"] == classification]
        for mode in ("sealed-detect", "self-directed"):
            members = [item for item in scope if item["update_mode"] == mode]
            compliant = sum(item["policy_compliance"]["compliant"] for item in members)
            rows.append(
                {
                    "classification": classification,
                    "update_mode": mode,
                    "metric_definition_version": METRIC_VERSION,
                    "numerator": compliant,
                    "denominator": len(members),
                    "invalid_count": sum(item["validity"]["status"] != "VALID" for item in members),
                    "missing_count": 0,
                    "rate": compliant / len(members) if members else None,
                }
            )
    return {
        "schema_version": 1,
        "artifact_type": "POLICY_MATRIX",
        "evaluation_id": plan["evaluation_id"],
        "rows": rows,
    }


def _behavior_matrix(behaviors: Sequence[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for item in behaviors:
        counts[item["transition"]] += 1
    return {
        "schema_version": 1,
        "artifact_type": "BEHAVIOR_MATRIX",
        "evaluation_id": plan["evaluation_id"],
        "metric_definition_version": METRIC_VERSION,
        "total": len(behaviors),
        "counts": dict(sorted(counts.items())),
        "records": [
            {
                "target_id": item["target_id"],
                "classification": item["classification"],
                "transition": item["transition"],
                "behavior_sha256": item["behavior_sha256"],
            }
            for item in behaviors
        ],
    }


def _publish_tree(destination: Path, files: dict[str, bytes]) -> str:
    normalized = {}
    for name, payload in files.items():
        normalized[_safe_path(name)] = payload
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise EvaluationError("EVALUATION_OUTPUT_INVALID", "Evaluation destination is not a real directory")
        actual = {
            path.relative_to(destination).as_posix(): path.read_bytes()
            for path in destination.rglob("*") if path.is_file() and not path.is_symlink()
        }
        if actual != normalized:
            raise EvaluationError("EVALUATION_OUTPUT_MISMATCH", "Existing evaluation package differs byte-for-byte")
        return "EXACT_MATCH"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        for name, payload in sorted(normalized.items()):
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        for directory in sorted(
            [path for path in temporary.rglob("*") if path.is_dir()],
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.replace(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return "PUBLISHED"


def _json_payload(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _existing_exact(
    destination: Path,
    *,
    plan: dict[str, Any],
    barrier_sha: str,
    ledger_sha: str,
    gold_sha: str,
) -> bool:
    manifest_path = destination / "evidence-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return False
    manifest = _read_json(manifest_path)
    _validate(
        manifest,
        destination.parents[4] / "schemas/host-evaluation-manifest-v1.schema.json",
        "EVALUATION_MANIFEST_INVALID",
    )
    _self_hash(manifest, "manifest_sha256")
    expected = manifest.get("source_commitments", {})
    if expected != {
        "evaluation_plan_sha256": canonical_sha256(plan),
        "batch_config_sha256": plan["batch_config"]["sha256"],
        "ledger_sha256": ledger_sha,
        "detect_barrier_sha256": barrier_sha,
        "gold_seal_sha256": gold_sha,
        "raw_source_sha256": plan["raw_source"]["sha256"],
    }:
        return False
    entries = manifest.get("output_files")
    if not isinstance(entries, list) or manifest.get("output_file_count") != len(entries):
        return False
    if manifest.get("output_files_sha256") != canonical_sha256(entries):
        return False
    expected_paths: set[str] = {"evidence-manifest.json"}
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        try:
            name = _safe_path(entry.get("path"))
        except EvaluationError:
            return False
        if name == "evidence-manifest.json" or name in expected_paths:
            return False
        path = destination.joinpath(*PurePosixPath(name).parts)
        if path.is_symlink() or not path.is_file():
            return False
        payload = path.read_bytes()
        if entry.get("size_bytes") != len(payload):
            return False
        if entry.get("sha256") != hashlib.sha256(payload).hexdigest():
            return False
        expected_paths.add(name)
    actual_paths = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    return actual_paths == expected_paths


def evaluate_host(
    *,
    config_path: Path,
    evaluation_plan_path: Path,
    bench: Path,
    repository_root: Path,
) -> dict[str, Any]:
    """Verify, construct delayed gold, score, execute behavior, and publish."""
    repository_root = repository_root.resolve()
    bench = bench.resolve()
    plan = _load_plan(evaluation_plan_path.resolve(), bench, repository_root)
    pinned_config = _repo_path(repository_root, plan["batch_config"]["path"])
    if config_path.resolve() != pinned_config.resolve():
        raise EvaluationError("EVALUATION_CONFIG_MISMATCH", "CLI config differs from evaluation plan")

    # Gold must not be read above this point. This call validates every final seal.
    config, targets, latest, manifests, barrier, ledger_sha = _verify_sealed_batch(
        config_path=pinned_config, bench=bench, repository_root=repository_root
    )
    store, _ = _construct_gold(
        plan=plan,
        config=config,
        targets=targets,
        barrier=barrier,
        bench=bench,
        repository_root=repository_root,
    )
    gold_sha = store["gold_seal_sha256"]
    destination = bench / "batch/runs" / config["batch_id"] / "evaluation" / plan["evaluation_id"]
    if destination.exists() and _existing_exact(
        destination,
        plan=plan,
        barrier_sha=barrier["barrier_sha256"],
        ledger_sha=ledger_sha,
        gold_sha=gold_sha,
    ):
        return {
            "schema_version": 1,
            "batch_id": config["batch_id"],
            "evaluation_id": plan["evaluation_id"],
            "status": "READY",
            "publication": "EXACT_MATCH",
            "output_path": destination.relative_to(repository_root).as_posix(),
        }

    files: dict[str, bytes] = {}
    evaluations: list[dict[str, Any]] = []
    behaviors: list[dict[str, Any]] = []
    detection_metrics: dict[tuple[str, str], dict[str, Any]] = {}
    for target in sorted(targets, key=lambda item: (item["stage"], target_key(item))):
        gold = _gold_task(store, target["task_id"])
        baseline = _baseline(bench, gold["base_sha"])
        manifest = manifests.get((target["task_id"], target["method"])) if target["stage"] == "detect" else None
        patch = None
        patch_sha = None
        if target["stage"] == "update":
            path = _attempt_path(target, latest[target_key(target)]["attempt"]) / "artifacts/candidate.patch"
            patch = path.read_text(encoding="utf-8")
            patch_sha = sha256_file(path)
        target_set, metrics, patch_paths, invalid = _target_sets_and_metrics(
            target=target,
            manifest=manifest,
            patch=patch,
            baseline=baseline,
            gold=gold,
            plan=plan,
        )
        target_set["gold_seal_sha256"] = gold_sha
        target_set["target_set_sha256"] = canonical_sha256(target_set)
        behavior = None
        behavior_path = None
        resource_sha = _resource_profile(bench, gold["base_sha"], plan)[1]
        patch_application_failed = False
        functional_failed = False
        if target["stage"] == "update":
            assert patch is not None
            behavior, logs = _evaluate_behavior(
                target=target,
                patch=patch,
                patch_paths=patch_paths,
                gold=gold,
                bench=bench,
                plan=plan,
            )
            behaviors.append(behavior)
            behavior_path = f"runs/{_target_id(target)}/behavior.json"
            files[behavior_path] = _json_payload(behavior)
            for environment, log in logs.items():
                files[f"runs/{_target_id(target)}/logs/{environment.lower()}.log"] = log.encode("utf-8")
            patch_application_failed = not behavior["patch_application_ok"]
            functional_failed = behavior["transition"] in {"FAILING", "INEFFECTIVE", "REGRESSIVE"}
        policy = {
            "status": "NOT_APPLICABLE" if target["stage"] == "detect" else "COMPLIANT",
            "compliant": target["stage"] == "update",
            "scope_violation_count": 0,
            "sealed_candidate_subset": (
                target["mode"] != "sealed-detect"
                or set(patch_paths).issubset({item["path"] for item in manifests[(target["task_id"], target["method"])]["candidates"]})
            ),
            "performance_advantage_inferred": False,
        }
        if target["stage"] == "detect":
            detection_metrics[(target["task_id"], target["method"])] = metrics
        handoff = None
        if target["stage"] == "update":
            detect = manifests[(target["task_id"], target["method"])]
            detect_files = [item["path"] for item in detect["candidates"]]
            overlap = len(set(detect_files) & set(patch_paths))
            handoff = {
                "causal": target["mode"] == "sealed-detect",
                "interpretation": "causal-handoff" if target["mode"] == "sealed-detect" else "post-hoc-non-causal-overlap",
                "detect_candidate_count": len(set(detect_files)),
                "update_file_count": len(set(patch_paths)),
                "overlap_count": overlap,
                "update_within_detect_rate": overlap / len(set(patch_paths)) if patch_paths else None,
            }
        attribution = choose_attribution(
            {
                "invalid_evidence": bool(invalid),
                "infrastructure_failure": behavior is not None and any(run["outcome"] in {"ERROR", "TIMEOUT", "COLLECTION_FAILURE"} for run in behavior["runs"]),
                "policy_violation": target["stage"] == "update" and not policy["compliant"],
                "localization_miss": target["stage"] == "detect" and metrics["file"]["any_hit"] == 0,
                "update_selection_miss": target["stage"] == "update" and metrics["file"]["any_hit"] == 0,
                "patch_application_failure": patch_application_failed,
                "functional_failure": functional_failed,
            }
        )
        evaluation = {
            "schema_version": 1,
            "artifact_type": "HOST_RUN_EVALUATION",
            "evaluation_id": plan["evaluation_id"],
            "target_id": _target_id(target),
            "target_key_sha256": hashlib.sha256(target_key(target).encode("utf-8")).hexdigest(),
            "stage": target["stage"],
            "task_id": target["task_id"],
            "classification": gold["classification"],
            "method": target["method"],
            "run_id": target["run_id"],
            "update_mode": target["mode"],
            "metric_definition_version": METRIC_VERSION,
            "validity": {"status": "VALID" if not invalid else "INVALID", "reason_ids": [hashlib.sha256(item.encode()).hexdigest()[:16] for item in invalid]},
            "policy_compliance": policy,
            "model_performance": metrics,
            "handoff": handoff,
            "execution": {
                "behavior_path": behavior_path,
                "behavior_sha256": behavior["behavior_sha256"] if behavior else None,
                "resource_profile_sha256": resource_sha,
                "project_tests_run_by_agent": False,
                "project_tests_run_by_host": behavior is not None,
            },
            "attribution": {"precedence": list(ATTRIBUTION_PRECEDENCE), "result": attribution},
            "provenance": {
                "base_sha": gold["base_sha"],
                "gold_seal_sha256": gold_sha,
                "sealed_artifact_sha256": patch_sha or manifest["seal"]["payload_sha256"],
                "ledger_sha256": ledger_sha,
                "detect_barrier_sha256": barrier["barrier_sha256"],
            },
        }
        evaluation["evaluation_sha256"] = canonical_sha256(evaluation)
        _validate(target_set, bench / "schemas/host-target-set-v1.schema.json", "TARGET_SET_INVALID")
        _validate(evaluation, bench / "schemas/host-run-evaluation-v1.schema.json", "RUN_EVALUATION_INVALID")
        run_root = f"runs/{_target_id(target)}"
        files[f"{run_root}/target-set.json"] = _json_payload(target_set)
        files[f"{run_root}/evaluation.json"] = _json_payload(evaluation)
        evaluations.append(evaluation)

    detect_matrix = {
        "schema_version": 1,
        "artifact_type": "MODEL_PERFORMANCE_MATRIX",
        "evaluation_id": plan["evaluation_id"],
        "stage": "detect",
        "metric_definition_version": METRIC_VERSION,
        "rows": aggregate_rows(evaluations, "detect"),
    }
    update_matrix = {
        "schema_version": 1,
        "artifact_type": "MODEL_PERFORMANCE_MATRIX",
        "evaluation_id": plan["evaluation_id"],
        "stage": "update",
        "metric_definition_version": METRIC_VERSION,
        "rows": aggregate_rows(evaluations, "update"),
    }
    behavior_matrix = _behavior_matrix(behaviors, plan)
    policy_matrix = _policy_matrix(evaluations, plan)
    paired = _paired(evaluations, plan)
    attribution_counts: dict[str, int] = defaultdict(int)
    for item in evaluations:
        attribution_counts[item["attribution"]["result"]] += 1
    failure_analysis = {
        "schema_version": 1,
        "artifact_type": "FAILURE_ANALYSIS",
        "evaluation_id": plan["evaluation_id"],
        "precedence": list(ATTRIBUTION_PRECEDENCE),
        "counts": dict(sorted(attribution_counts.items())),
        "records": [{"target_id": item["target_id"], "result": item["attribution"]["result"]} for item in evaluations],
    }
    all_update = next(row for row in update_matrix["rows"] if row["classification"] == "ALL" and row["dimensions"] == {})
    all_policy = [row for row in policy_matrix["rows"] if row["classification"] == "ALL"]
    policy_num = sum(row["numerator"] for row in all_policy)
    policy_den = sum(row["denominator"] for row in all_policy)
    mixed_behaviors = [item for item in behaviors if item["classification"] == "MIXED_CODE_AND_TEST_PR"]
    discriminating = sum(item["transition"] == "DISCRIMINATING" for item in mixed_behaviors)
    regressions = sum(item["transition"] == "REGRESSIVE" for item in behaviors)
    gates = {
        "integrity_coverage": len(evaluations) == plan["gates"]["sealed_target_count"],
        "gold_validity": sum(item["validity"]["status"] != "VALID" for item in evaluations) <= plan["gates"]["gold_invalid_max"],
        "policy_compliance": (policy_num / policy_den if policy_den else 0.0) >= plan["gates"]["policy_compliance_min"],
        "quality": (all_update["file"]["macro"]["f1"] or 0.0) >= plan["gates"]["update_file_macro_f1_min"],
        "mixed_discrimination": (discriminating / len(mixed_behaviors) if mixed_behaviors else 0.0) >= plan["gates"]["mixed_discrimination_min"],
        "regression": regressions <= plan["gates"]["regression_max"],
        "paired_coverage": paired["eligible_pair_count"] >= plan["gates"]["eligible_pair_count_min"],
    }
    if all(gates.values()):
        recommendation = "GO"
    elif gates["integrity_coverage"] and gates["gold_validity"]:
        recommendation = "NO_GO"
    else:
        recommendation = "INCONCLUSIVE"
    go_no_go = {
        "schema_version": 1,
        "artifact_type": "EXPANSION_RECOMMENDATION",
        "evaluation_id": plan["evaluation_id"],
        "target_batch_size": 98,
        "recommendation": recommendation,
        "gates": gates,
        "failed_gates": sorted(name for name, passed in gates.items() if not passed),
    }
    pilot = {
        "schema_version": 1,
        "artifact_type": "PILOT_EVALUATION_REPORT",
        "evaluation_id": plan["evaluation_id"],
        "batch_id": config["batch_id"],
        "evaluator_version": EVALUATOR_VERSION,
        "metric_definition_version": METRIC_VERSION,
        "status": "COMPLETE",
        "counts": {
            "detect_evaluations": sum(item["stage"] == "detect" for item in evaluations),
            "update_evaluations": sum(item["stage"] == "update" for item in evaluations),
            "behavior_evaluations": len(behaviors),
            "invalid_evaluations": sum(item["validity"]["status"] != "VALID" for item in evaluations),
            "eligible_pairs": paired["eligible_pair_count"],
        },
        "recommendation": recommendation,
        "limitations": [
            "Three PRs do not support inferential significance claims.",
            "Self-directed Detect overlap is post-hoc and non-causal.",
            "Legacy Prompt 9 Update workspaces remain outside the v1 seal and were not used.",
        ],
        "gold_values_published": False,
        "hidden_production_patch_published": False,
    }
    viewer = {
        "schema_version": 1,
        "evaluation_id": plan["evaluation_id"],
        "status": pilot["status"],
        "counts": pilot["counts"],
        "recommendation": recommendation,
        "detect_rows": detect_matrix["rows"],
        "update_rows": update_matrix["rows"],
        "behavior_counts": behavior_matrix["counts"],
        "policy_rows": policy_matrix["rows"],
    }
    documents = {
        "matrices/detect.json": detect_matrix,
        "matrices/update.json": update_matrix,
        "matrices/end-to-end.json": behavior_matrix,
        "matrices/policy.json": policy_matrix,
        "paired-comparisons.json": paired,
        "failure-analysis.json": failure_analysis,
        "pilot-report.json": pilot,
        "go-no-go.json": go_no_go,
        "viewer/data.json": viewer,
    }
    for name, value in documents.items():
        files[name] = _json_payload(value)
    viewer_html = """<!doctype html><meta charset=\"utf-8\"><title>SDD pilot evaluation</title><main><h1>SDD pilot evaluation</h1><pre id=\"data\"></pre></main><script>fetch('data.json').then(r=>r.json()).then(v=>data.textContent=JSON.stringify(v,null,2))</script>\n"""
    files["viewer/index.html"] = viewer_html.encode("utf-8")
    output_entries = [
        {"path": name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for name, payload in sorted(files.items())
    ]
    manifest = {
        "schema_version": 1,
        "artifact_type": "HOST_EVALUATION_EVIDENCE_MANIFEST",
        "evaluation_id": plan["evaluation_id"],
        "batch_id": config["batch_id"],
        "source_commitments": {
            "evaluation_plan_sha256": canonical_sha256(plan),
            "batch_config_sha256": plan["batch_config"]["sha256"],
            "ledger_sha256": ledger_sha,
            "detect_barrier_sha256": barrier["barrier_sha256"],
            "gold_seal_sha256": gold_sha,
            "raw_source_sha256": plan["raw_source"]["sha256"],
        },
        "output_file_count": len(output_entries),
        "output_files": output_entries,
        "output_files_sha256": canonical_sha256(output_entries),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    files["evidence-manifest.json"] = _json_payload(manifest)

    forbidden = [item["patch"] for task in store["tasks"] for item in task["production_patches"]]
    public_blob = b"\n".join(files.values()).decode("utf-8", errors="replace")
    if any(value and value in public_blob for value in forbidden):
        raise EvaluationError("HIDDEN_PATCH_LEAK", "Published evaluation contains hidden production patch bytes")
    _validate(manifest, bench / "schemas/host-evaluation-manifest-v1.schema.json", "EVALUATION_MANIFEST_INVALID")
    ledger_path = bench / "batch/runs" / config["batch_id"] / "ledger.jsonl"
    if sha256_file(ledger_path) != ledger_sha:
        raise EvaluationError("LEDGER_MUTATED", "Ledger changed during host evaluation")
    publication = _publish_tree(destination, files)
    if sha256_file(ledger_path) != ledger_sha:
        raise EvaluationError("LEDGER_MUTATED", "Ledger changed during evaluation publication")
    return {
        "schema_version": 1,
        "batch_id": config["batch_id"],
        "evaluation_id": plan["evaluation_id"],
        "status": "READY",
        "publication": publication,
        "recommendation": recommendation,
        "output_path": destination.relative_to(repository_root).as_posix(),
    }
