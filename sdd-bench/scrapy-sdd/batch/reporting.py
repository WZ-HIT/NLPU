"""Deterministic, read-only final reporting for a completed SDD batch."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from .core import BatchError, canonical_sha256, sha256_file
from .orchestrator import Ledger, _latest, target_key, validate_batch_config, validate_prepared_manifest
from .result_view import build as build_result_view

REPORT_NAMES = ("report.json", "audit.json", "evidence-manifest.json")
FAILURE_CLASSES = ("infrastructure", "runtime", "output", "scope", "unknown")


class ReportingError(BatchError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(code, message, **details)


class Evidence:
    """Read evidence inside the repository while recording byte commitments."""

    def __init__(self, repository_root: Path) -> None:
        self.root = repository_root.resolve()
        self.files: dict[str, dict[str, Any]] = {}

    def path(self, path: Path, *, allow_workspace: bool = False) -> Path:
        if path.is_symlink() or not path.is_file():
            raise ReportingError("EVIDENCE_FILE_INVALID", "Evidence must be a regular non-symlink file", path=str(path))
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise ReportingError("EVIDENCE_PATH_ESCAPE", "Evidence path escapes repository", path=str(path)) from exc
        if "gold" in relative.parts:
            raise ReportingError("GOLD_PATH_FORBIDDEN", "Final reporting may not read batch gold", path=relative.as_posix())
        if not allow_workspace and "workspace" in relative.parts:
            raise ReportingError("WORKSPACE_PATH_FORBIDDEN", "Excluded Update workspaces are not report evidence", path=relative.as_posix())
        return resolved

    def add(self, path: Path) -> Path:
        resolved = self.path(path)
        relative = resolved.relative_to(self.root).as_posix()
        self.files[relative] = {
            "path": relative,
            "size_bytes": resolved.stat().st_size,
            "sha256": sha256_file(resolved),
        }
        return resolved

    def json(self, path: Path) -> dict[str, Any]:
        resolved = self.add(path)
        try:
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReportingError("EVIDENCE_JSON_INVALID", "Evidence is not valid JSON", path=str(path)) from exc
        if not isinstance(value, dict):
            raise ReportingError("EVIDENCE_JSON_INVALID", "Evidence JSON must be an object", path=str(path))
        return value

    def text(self, path: Path) -> str:
        return self.add(path).read_text(encoding="utf-8")


def _validate(value: dict[str, Any], schema: Path, code: str) -> None:
    validator = Draft202012Validator(
        json.loads(schema.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise ReportingError(code, "JSON document failed schema validation", errors=[error.message for error in errors])


def _self_hash(value: dict[str, Any], field: str, context: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if not isinstance(supplied, str) or supplied != canonical_sha256(payload):
        raise ReportingError("SELF_HASH_MISMATCH", "Canonical self-hash differs", context=context, field=field)


def _safe_repo_path(repository_root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or "\\" in value or "//" in value:
        raise ReportingError("UNSAFE_EVIDENCE_PATH", "Repository-relative evidence path is unsafe", path=value)
    path = repository_root.joinpath(*pure.parts)
    try:
        path.resolve().relative_to(repository_root.resolve())
    except ValueError as exc:
        raise ReportingError("EVIDENCE_PATH_ESCAPE", "Evidence path escapes repository", path=value) from exc
    return path


def _file_manifest(root: Path, evidence: Evidence) -> tuple[list[dict[str, Any]], str]:
    if root.is_symlink() or not root.is_dir():
        raise ReportingError("EVIDENCE_DIRECTORY_INVALID", "Evidence directory must be real", path=str(root))
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ReportingError("EVIDENCE_SYMLINK", "Sealed evidence contains a symlink", path=relative)
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReportingError("EVIDENCE_SPECIAL_FILE", "Sealed evidence contains a special file", path=relative)
        evidence.add(path)
        entries.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return entries, canonical_sha256(entries)


def _check_artifact(path: Path, expected_sha: str, evidence: Evidence, context: str) -> None:
    actual = sha256_file(evidence.add(path))
    if actual != expected_sha:
        raise ReportingError("ARTIFACT_HASH_MISMATCH", "Artifact SHA-256 differs", context=context, expected=expected_sha, actual=actual)


def _attempt_path(target: dict[str, Any], attempt: int) -> Path:
    task_root = target["task_manifest"].parent
    root = task_root / "runs" / target["method"] / target["stage"] / "executions" / target["run_id"] / f"attempt-{attempt}"
    return root if target["stage"] == "detect" else root / f"mode-{target['mode']}"


def _verify_detection(
    target: dict[str, Any], event: dict[str, Any], bench: Path, repository_root: Path,
    evidence: Evidence,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    execution = _attempt_path(target, event["attempt"])
    expected = target["task_manifest"].parent / "runs" / target["method"] / "detect" / "executions" / target["run_id"] / f"attempt-{event['attempt']}"
    if execution.resolve() != expected.resolve():
        raise ReportingError("ATTEMPT_PATH_MISMATCH", "Detect attempt path is not canonical")
    manifest_path = execution / "detection-manifest.json"
    summary_path = execution / "detect-summary.json"
    checkpoint_path = execution / "checkpoint.json"
    seal_path = execution / "seal.json"
    manifest = evidence.json(manifest_path)
    summary = evidence.json(summary_path)
    checkpoint = evidence.json(checkpoint_path)
    seal = evidence.json(seal_path)
    _validate(manifest, bench / ("schemas/detection-v2.schema.json" if manifest.get("schema_version") == 2 else "schemas/detection-v1.schema.json"), "DETECTION_SCHEMA_INVALID")
    _validate(checkpoint, bench / "schemas/stage-execution-v1.schema.json", "CHECKPOINT_SCHEMA_INVALID")
    payload = dict(manifest)
    manifest_seal = payload.pop("seal", None)
    if not isinstance(manifest_seal, dict) or manifest_seal.get("payload_sha256") != canonical_sha256(payload):
        raise ReportingError("DETECTION_MANIFEST_SEAL_INVALID", "Detection manifest payload seal differs", target=target_key(target))
    _self_hash(summary, "summary_sha256", target_key(target))
    _self_hash(seal, "seal_sha256", target_key(target))
    if any((manifest.get("task_id") != target["task_id"], manifest.get("method") != target["method"], manifest.get("producer", {}).get("run_id") != target["run_id"])):
        raise ReportingError("DETECTION_CONTEXT_MISMATCH", "Detection manifest target identity differs", target=target_key(target))
    if summary.get("status") != "SEALED" or summary.get("project_code_changed") is not False or summary.get("tests_run") is not False:
        raise ReportingError("DETECTION_SUMMARY_INVALID", "Detect summary violates sealed no-change semantics", target=target_key(target))
    if checkpoint.get("status") != "SEALED" or checkpoint.get("tests_run") is not False or checkpoint.get("stage") != "detect":
        raise ReportingError("DETECTION_CHECKPOINT_INVALID", "Detect checkpoint is not sealed", target=target_key(target))
    sealed_root = target["task_manifest"].parent / "runs" / target["method"] / "update" / "sealed-input"
    sealed_manifest = evidence.json(sealed_root / "detection-manifest.json")
    if sealed_manifest != manifest:
        raise ReportingError("SEALED_INPUT_MISMATCH", "Detect execution and sealed-input manifests differ", target=target_key(target))
    planning_entries, planning_sha = _file_manifest(sealed_root / "planning-artifacts", evidence)
    execution_planning_entries, execution_planning_sha = _file_manifest(execution / "sdd-artifacts", evidence)
    if planning_entries != execution_planning_entries or planning_sha != execution_planning_sha:
        raise ReportingError("PLANNING_ARTIFACT_MISMATCH", "Detect planning copies differ", target=target_key(target))
    if manifest.get("planning_artifacts") != {"file_count": len(planning_entries), "manifest_sha256": planning_sha}:
        raise ReportingError("PLANNING_MANIFEST_MISMATCH", "Detection planning manifest differs", target=target_key(target))
    if summary.get("detection_manifest_sha256") != sha256_file(manifest_path) or summary.get("planning_artifacts_sha256") != planning_sha:
        raise ReportingError("DETECTION_PROVENANCE_MISMATCH", "Detect summary provenance differs", target=target_key(target))
    bundle_entries: list[dict[str, Any]] = []
    for path in sorted(execution.rglob("*")):
        if path == seal_path or path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise ReportingError("DETECTION_BUNDLE_INVALID", "Detect bundle has non-regular evidence", path=str(path))
        evidence.add(path)
        bundle_entries.append({"path": path.relative_to(execution).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if seal.get("seal_type") != "IMMUTABLE_DETECTION_BUNDLE" or seal.get("file_count") != len(bundle_entries) or seal.get("files_manifest_sha256") != canonical_sha256(bundle_entries):
        raise ReportingError("DETECTION_BUNDLE_SEAL_INVALID", "Detect bundle manifest differs", target=target_key(target))
    candidates = sorted({item["path"] for item in manifest.get("candidates", [])})
    return ({
        "target": target_key(target), "task_id": target["task_id"], "method": target["method"],
        "run_id": target["run_id"], "attempt": event["attempt"], "status": "SEALED",
        "candidate_test_file_count": len(candidates), "planning_artifact_file_count": len(planning_entries),
        "execution_path": execution.relative_to(repository_root).as_posix(),
    }, manifest, [{"id": name, "status": "PASS"} for name in (
        "terminal-ledger-state", "canonical-attempt-path", "manifest-schema-and-seal", "no-project-change",
        "project-tests-not-run", "sealed-planning-copy", "checkpoint-provenance", "bundle-seal",
    )])


def _patch_paths(text: str) -> list[str]:
    paths: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("+++ "):
            continue
        value = line[4:].split("\t", 1)[0]
        if value == "/dev/null":
            continue
        if value.startswith("b/"):
            value = value[2:]
        paths.add(value)
    return sorted(paths)


def _tests_only(paths: Iterable[str], context: str) -> None:
    for value in paths:
        pure = PurePosixPath(value)
        if not value or pure.is_absolute() or ".." in pure.parts or "\\" in value or not pure.parts or pure.parts[0] not in {"test", "tests", "testing"}:
            raise ReportingError("UPDATE_SCOPE_INVALID", "Update evidence contains a non-test path", context=context, path=value)


def _verify_update(
    target: dict[str, Any], event: dict[str, Any], detection: dict[str, Any], bench: Path,
    repository_root: Path, evidence: Evidence,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    execution = _attempt_path(target, event["attempt"])
    if execution.is_symlink() or not execution.is_dir():
        raise ReportingError("ATTEMPT_PATH_MISSING", "Final Update attempt directory is missing", target=target_key(target))
    modified_path = execution / "candidate-modified-files.json"
    summary_path = execution / "update-summary.json"
    reference_path = execution / "policy-reference.json"
    checkpoint_path = execution / "checkpoint.json"
    scope_path = execution / "artifacts/scope-audit.json"
    patch_path = execution / "artifacts/candidate.patch"
    compose_path = execution / "artifacts/rendered-compose.yaml"
    seal_path = execution / "seal.json"
    modified = evidence.json(modified_path)
    summary = evidence.json(summary_path)
    reference = evidence.json(reference_path)
    checkpoint = evidence.json(checkpoint_path)
    scope = evidence.json(scope_path)
    seal = evidence.json(seal_path)
    patch = evidence.text(patch_path)
    compose = evidence.text(compose_path)
    policy = evidence.json(target["policy"])
    _validate(checkpoint, bench / "schemas/stage-execution-v1.schema.json", "CHECKPOINT_SCHEMA_INVALID")
    for document, field in ((modified, "manifest_sha256"), (summary, "summary_sha256"), (reference, "reference_sha256"), (seal, "seal_sha256")):
        _self_hash(document, field, target_key(target))
    identity = (target["task_id"], target["method"], target["run_id"], target["mode"])
    for document in (modified, summary):
        actual = (document.get("task_id"), document.get("method"), document.get("update_run_id"), document.get("update_mode"))
        if actual != identity:
            raise ReportingError("UPDATE_CONTEXT_MISMATCH", "Update evidence target identity differs", target=target_key(target))
    if (reference.get("task_id"), reference.get("method"), reference.get("run_id"), reference.get("mode")) != identity:
        raise ReportingError("UPDATE_CONTEXT_MISMATCH", "Policy reference target identity differs", target=target_key(target))
    if policy.get("mode") != target["mode"] or policy.get("run_id") != target["run_id"]:
        raise ReportingError("UPDATE_POLICY_CONTEXT_MISMATCH", "Update policy context differs", target=target_key(target))
    _check_artifact(target["policy"], target["policy_sha256"], evidence, target_key(target))
    if reference.get("policy_sha256") != target["policy_sha256"] or summary.get("update_policy_sha256") != target["policy_sha256"]:
        raise ReportingError("UPDATE_POLICY_HASH_MISMATCH", "Update policy commitment differs", target=target_key(target))
    detection_sha = sha256_file(target["task_manifest"].parent / "runs" / target["method"] / "update/sealed-input/detection-manifest.json")
    if modified.get("detection_manifest_sha256") != detection_sha or summary.get("detection_manifest_sha256") != detection_sha:
        raise ReportingError("UPDATE_DETECTION_HASH_MISMATCH", "Update detection commitment differs", target=target_key(target))
    modified_files = modified.get("candidate_modified_test_files")
    if not isinstance(modified_files, list):
        raise ReportingError("UPDATE_MODIFIED_MANIFEST_INVALID", "Modified-file list is absent", target=target_key(target))
    modified_paths = sorted(item.get("path") for item in modified_files if isinstance(item, dict) and isinstance(item.get("path"), str))
    changed_paths = scope.get("changed_paths")
    violations = scope.get("violations")
    if not isinstance(changed_paths, list) or not all(isinstance(path, str) for path in changed_paths) or violations != []:
        raise ReportingError("UPDATE_SCOPE_INVALID", "Final scope audit is not violation-free", target=target_key(target))
    _tests_only(changed_paths, target_key(target))
    _tests_only(modified_paths, target_key(target))
    patch_paths = _patch_paths(patch)
    _tests_only(patch_paths, target_key(target))
    if modified_paths != sorted(changed_paths) or patch_paths != modified_paths:
        raise ReportingError("UPDATE_PATCH_MANIFEST_MISMATCH", "Patch, scope, and modified-file paths differ", target=target_key(target))
    candidates = sorted(item["path"] for item in detection.get("candidates", []))
    if target["mode"] == "sealed-detect" and not set(changed_paths).issubset(candidates):
        raise ReportingError("SEALED_CANDIDATE_SCOPE_INVALID", "sealed-detect changed a path outside candidates", target=target_key(target))
    if summary.get("status") != "SEALED" or summary.get("tests_run") is not False or summary.get("violations") != []:
        raise ReportingError("UPDATE_SUMMARY_INVALID", "Update summary is not sealed and violation-free", target=target_key(target))
    if summary.get("candidate_patch_sha256") != sha256_file(patch_path) or summary.get("candidate_modified_test_file_count") != len(modified_paths):
        raise ReportingError("UPDATE_SUMMARY_PROVENANCE_INVALID", "Update summary patch metrics differ", target=target_key(target))
    if checkpoint.get("stage") != "update" or checkpoint.get("status") != "SEALED" or checkpoint.get("tests_run") is not False:
        raise ReportingError("UPDATE_CHECKPOINT_INVALID", "Update checkpoint is not sealed", target=target_key(target))
    if checkpoint.get("provenance", {}).get("compose_rendered_sha256") != sha256_file(compose_path):
        raise ReportingError("UPDATE_COMPOSE_HASH_MISMATCH", "Rendered Compose commitment differs", target=target_key(target))
    if target["mode"] == "self-directed":
        forbidden = ("/input/detection-manifest.json", "update/sealed-input", "planning-artifacts", "UPDATE_SEALED_PLANNING", "UPDATE_DETECTION_TARGET")
        present = [marker for marker in forbidden if marker in compose]
        if present:
            raise ReportingError("SELF_DIRECTED_DETECT_LEAK", "self-directed Compose exposes Detect evidence", target=target_key(target), markers=present)
        if summary.get("detection_visible_to_agent") is not False or summary.get("sealed_planning_visible_to_agent") is not False:
            raise ReportingError("SELF_DIRECTED_DETECT_LEAK", "self-directed summary claims Detect visibility", target=target_key(target))
    else:
        if summary.get("detection_visible_to_agent") is not True or summary.get("sealed_planning_visible_to_agent") is not True:
            raise ReportingError("SEALED_INPUT_VISIBILITY_INVALID", "sealed-detect visibility evidence differs", target=target_key(target))
    bundle_entries: list[dict[str, Any]] = []
    for root in sorted(execution.iterdir()):
        if root.name in {"workspace", "seal.json"}:
            continue
        if root.is_symlink():
            raise ReportingError("UPDATE_BUNDLE_INVALID", "Update bundle root is a symlink", path=str(root))
        if root.is_file():
            evidence.add(root)
            bundle_entries.append({"path": root.name, "sha256": sha256_file(root)})
        elif root.is_dir():
            entries, manifest_sha = _file_manifest(root, evidence)
            bundle_entries.append({"path": root.name + "/", "file_count": len(entries), "sha256": manifest_sha})
        else:
            raise ReportingError("UPDATE_BUNDLE_INVALID", "Update bundle has a special root", path=str(root))
    if seal.get("seal_type") != "IMMUTABLE_UPDATE_BUNDLE" or seal.get("bundle_manifest_sha256") != canonical_sha256(bundle_entries) or seal.get("entry_count") != len(bundle_entries) or seal.get("status") != "SEALED":
        raise ReportingError("UPDATE_BUNDLE_SEAL_INVALID", "Update bundle manifest differs", target=target_key(target))
    sdd_status = "NOT_CAPTURED_BY_V1_RUNNER"
    sdd_manifest_path = execution / "sdd-artifacts-manifest.json"
    if sdd_manifest_path.exists():
        sdd_manifest = evidence.json(sdd_manifest_path)
        _validate(sdd_manifest, bench / "schemas/update-sdd-artifacts-v1.schema.json", "UPDATE_SDD_ARTIFACTS_SCHEMA_INVALID")
        _self_hash(sdd_manifest, "manifest_sha256", target_key(target))
        entries, entries_sha = _file_manifest(execution / "sdd-artifacts", evidence)
        if entries != sdd_manifest.get("files") or entries_sha != sdd_manifest.get("files_manifest_sha256") or len(entries) != sdd_manifest.get("file_count"):
            raise ReportingError("UPDATE_SDD_ARTIFACTS_MISMATCH", "Captured Update SDD artifacts differ", target=target_key(target))
        sdd_status = sdd_manifest["status"]
        if summary.get("sdd_artifacts_status") != sdd_status or summary.get("sdd_artifacts_manifest_sha256") != sha256_file(sdd_manifest_path):
            raise ReportingError("UPDATE_SDD_ARTIFACTS_PROVENANCE_INVALID", "Update summary SDD artifact commitment differs", target=target_key(target))
    return ({
        "target": target_key(target), "task_id": target["task_id"], "method": target["method"],
        "run_id": target["run_id"], "update_mode": target["mode"], "attempt": event["attempt"],
        "status": "SEALED", "modified_test_file_count": len(modified_paths), "scope_violation_count": 0,
        "sdd_artifacts_status": sdd_status, "workspace_seal_status": "EXCLUDED",
        "execution_path": execution.relative_to(repository_root).as_posix(),
    }, [{"id": name, "status": "PASS"} for name in (
        "terminal-ledger-state", "canonical-attempt-path", "policy-hash-and-context", "detection-provenance",
        "tests-only-scope", "mode-specific-scope", "patch-manifest-consistency", "project-tests-not-run",
        "compose-isolation", "checkpoint-provenance", "bundle-seal",
    )])


def _verify_barrier(config: dict[str, Any], detect_targets: list[dict[str, Any]], run_root: Path, repository_root: Path, evidence: Evidence) -> dict[str, Any]:
    barrier = evidence.json(run_root / "detect-barrier.json")
    _self_hash(barrier, "barrier_sha256", "global Detect barrier")
    if barrier.get("status") != "SEALED" or barrier.get("batch_id") != config["batch_id"] or barrier.get("detect_count") != len(detect_targets) or barrier.get("expected_detect_count") != len(detect_targets):
        raise ReportingError("DETECT_BARRIER_INVALID", "Global Detect barrier counts or context differ")
    expected = {(target["task_id"], target["method"], target["run_id"]) for target in detect_targets}
    actual: set[tuple[str, str, str]] = set()
    for record in barrier.get("records", []):
        key = (record.get("task_id"), record.get("method"), record.get("run_id"))
        actual.add(key)
        reference = record.get("detection_manifest", {})
        if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
            raise ReportingError("DETECT_BARRIER_INVALID", "Barrier manifest reference is invalid")
        path = _safe_repo_path(repository_root, reference["path"])
        _check_artifact(path, reference.get("sha256", ""), evidence, "global Detect barrier")
        manifest = evidence.json(path)
        if reference.get("seal_sha256") != manifest.get("seal", {}).get("payload_sha256"):
            raise ReportingError("DETECT_BARRIER_INVALID", "Barrier manifest seal commitment differs")
    if actual != expected:
        raise ReportingError("DETECT_BARRIER_INVALID", "Barrier target universe differs", expected=sorted(expected), actual=sorted(actual))
    return barrier


def _classify_failure(target: dict[str, Any], event: dict[str, Any], repository_root: Path, evidence: Evidence) -> dict[str, Any]:
    execution = _attempt_path(target, event["attempt"])
    references: list[dict[str, Any]] = []
    texts: list[str] = []
    scope_violation = False
    if execution.is_dir() and not execution.is_symlink():
        for path in sorted(execution.rglob("*")):
            relative_parts = path.relative_to(execution).parts
            if "workspace" in relative_parts or path.is_symlink() or not path.is_file():
                continue
            evidence.add(path)
            references.append({"path": path.relative_to(repository_root).as_posix(), "sha256": sha256_file(path)})
            if path.name in {"agent.stderr.log", "agent.jsonl"}:
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
            if path.name == "scope-audit.json":
                try:
                    scope_violation = bool(json.loads(path.read_text(encoding="utf-8")).get("violations"))
                except json.JSONDecodeError:
                    pass
    joined = "\n".join(texts).lower()
    if scope_violation:
        category = "scope"
    elif any(marker in joined for marker in ("oci runtime", "error mounting", "failed to create task", "no such file or directory")):
        category = "infrastructure"
    elif '"type":"turn.completed"' in joined and not (execution / "seal.json").exists():
        category = "output"
    elif texts:
        category = "runtime"
    else:
        category = "unknown"
    return {
        "sequence": event["sequence"], "target": target_key(target), "stage": target["stage"],
        "attempt": event["attempt"], "classification": category,
        "attempt_path": execution.relative_to(repository_root).as_posix(), "evidence": references,
    }


def _aggregate(rows: list[dict[str, Any]], dimension_names: tuple[str, ...], metric_names: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[name] for name in dimension_names)].append(row)
    result: list[dict[str, Any]] = []
    for values, members in sorted(groups.items()):
        result.append({
            "dimensions": dict(zip(dimension_names, values)),
            "metrics": {name: sum(int(member.get(name, 0)) for member in members) for name in metric_names},
        })
    return result


def _aggregates(detect: list[dict[str, Any]], update: list[dict[str, Any]], failures: list[dict[str, Any]], classifications: dict[str, str]) -> dict[str, Any]:
    failed_by_target = Counter(item["target"] for item in failures)
    detect_rows = [{**row, "classification": classifications[row["task_id"]], "configured": 1, "sealed": 1, "historical_failed_events": failed_by_target[row["target"]]} for row in detect]
    update_rows = [{**row, "classification": classifications[row["task_id"]], "configured": 1, "sealed": 1, "historical_failed_events": failed_by_target[row["target"]]} for row in update]
    pair_rows: list[dict[str, Any]] = []
    for row in detect_rows:
        updates = [item for item in update_rows if item["task_id"] == row["task_id"] and item["method"] == row["method"]]
        pair_rows.append({
            "classification": row["classification"], "method": row["method"], "configured_pairs": 1,
            "ready_pairs": int(bool(updates) and all(item["sealed"] for item in updates)),
            "historical_failed_events": row["historical_failed_events"] + sum(item["historical_failed_events"] for item in updates),
        })
    detect_metrics = ("configured", "sealed", "historical_failed_events", "candidate_test_file_count", "planning_artifact_file_count")
    update_metrics = ("configured", "sealed", "historical_failed_events", "modified_test_file_count", "scope_violation_count")
    pair_metrics = ("configured_pairs", "ready_pairs", "historical_failed_events")
    return {
        "detect": {
            "overall": _aggregate(detect_rows, tuple(), detect_metrics),
            "by_classification": _aggregate(detect_rows, ("classification",), detect_metrics),
            "by_method": _aggregate(detect_rows, ("method",), detect_metrics),
            "by_classification_method": _aggregate(detect_rows, ("classification", "method"), detect_metrics),
        },
        "update": {
            "overall": _aggregate(update_rows, tuple(), update_metrics),
            "by_classification": _aggregate(update_rows, ("classification",), update_metrics),
            "by_method": _aggregate(update_rows, ("method",), update_metrics),
            "by_mode": _aggregate(update_rows, ("update_mode",), update_metrics),
            "by_classification_method": _aggregate(update_rows, ("classification", "method"), update_metrics),
            "by_classification_method_mode": _aggregate(update_rows, ("classification", "method", "update_mode"), update_metrics),
        },
        "end_to_end": {
            "overall": _aggregate(pair_rows, tuple(), pair_metrics),
            "by_classification": _aggregate(pair_rows, ("classification",), pair_metrics),
            "by_method": _aggregate(pair_rows, ("method",), pair_metrics),
            "by_classification_method": _aggregate(pair_rows, ("classification", "method"), pair_metrics),
        },
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _publish(final_dir: Path, documents: dict[str, dict[str, Any]]) -> str:
    payloads = {name: _json_bytes(documents[name]) for name in REPORT_NAMES}
    if final_dir.exists():
        if final_dir.is_symlink() or not final_dir.is_dir():
            raise ReportingError("FINAL_OUTPUT_INVALID", "Final output path is not a real directory")
        actual_names = sorted(path.name for path in final_dir.iterdir())
        if actual_names != sorted(REPORT_NAMES) or any((final_dir / name).read_bytes() != payload for name, payload in payloads.items()):
            raise ReportingError("FINAL_OUTPUT_MISMATCH", "Existing final package is not byte-for-byte identical")
        return "EXACT_MATCH"
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".final-", dir=final_dir.parent))
    try:
        for name in REPORT_NAMES:
            with (temporary / name).open("wb") as handle:
                handle.write(payloads[name])
                handle.flush()
                os.fsync(handle.fileno())
        directory_fd = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.replace(temporary, final_dir)
        parent_fd = os.open(final_dir.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return "PUBLISHED"


def generate_final_evidence(*, config_path: Path | None = None, manifest_path: Path | None = None, bench: Path, repository_root: Path) -> dict[str, Any]:
    """Verify the complete configured batch and atomically publish final evidence."""
    repository_root = repository_root.resolve()
    bench = bench.resolve()
    if (config_path is None) == (manifest_path is None):
        raise ReportingError("RUN_SOURCE_REQUIRED", "Exactly one batch config or prepared manifest is required")
    source_path = (manifest_path or config_path).resolve()
    evidence = Evidence(repository_root)
    evidence.add(source_path)
    if manifest_path is not None:
        config, targets = validate_prepared_manifest(source_path, bench, repository_root)
    else:
        config, targets = validate_batch_config(source_path, bench, repository_root)
    result_view = build_result_view(source_path, bench, repository_root)
    if set(result_view["targets"]) != {target_key(item) for item in targets}:
        raise ReportingError("TARGET_UNIVERSE_INVALID", "Result view differs from configured targets")
    run_root = bench / "batch/runs" / config["batch_id"]
    ledger_path = run_root / "ledger.jsonl"
    ledger_before = sha256_file(evidence.add(ledger_path))
    ledger = Ledger(ledger_path, config["batch_id"], bench / "schemas/batch-ledger-event-v1.schema.json")
    events = ledger.read()
    latest = _latest(events)
    for target in targets:
        event = latest.get(target_key(target))
        expected = "DETECT_SEALED" if target["stage"] == "detect" else "UPDATE_SEALED"
        if event is None or event.get("state") != expected:
            raise ReportingError("TARGET_NOT_SEALED", "Configured target is not terminal sealed", target=target_key(target))
    detect_targets = [target for target in targets if target["stage"] == "detect"]
    update_targets = [target for target in targets if target["stage"] == "update"]
    barrier = _verify_barrier(config, detect_targets, run_root, repository_root, evidence)
    approvals = config.get("approved_plans") or [config["approved_plan"]]
    classifications = {}
    for approved in approvals:
        plan_path = _safe_repo_path(repository_root, approved["path"])
        plan = evidence.json(plan_path)
        _check_artifact(plan_path, approved["sha256"], evidence, "approved plan")
        for item in plan.get("tasks", []):
            if item["task_id"] in classifications and classifications[item["task_id"]] != item["classification"]:
                raise ReportingError("PLAN_CLASSIFICATION_INVALID", "Approved plans disagree on task classification")
            classifications[item["task_id"]] = item["classification"]
    classifications = {task_id: value for task_id, value in classifications.items() if task_id in {target["task_id"] for target in targets}}
    if set(classifications) != {target["task_id"] for target in targets}:
        raise ReportingError("PLAN_CLASSIFICATION_INVALID", "Approved plan classifications do not cover configured tasks")
    detect_records: list[dict[str, Any]] = []
    detection_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    audit_targets: list[dict[str, Any]] = []
    for target in sorted(detect_targets, key=target_key):
        record, manifest, checks = _verify_detection(target, latest[target_key(target)], bench, repository_root, evidence)
        indexed = result_view["targets"][target_key(target)]
        record.update({"target_id": indexed["target_id"], "ledger_event": indexed["ledger_event"], "seal": indexed["seal"]})
        detect_records.append(record)
        detection_by_pair[(target["task_id"], target["method"])] = manifest
        audit_targets.append({"target": target_key(target), "stage": "detect", "status": "PASS", "checks": checks})
    update_records: list[dict[str, Any]] = []
    for target in sorted(update_targets, key=target_key):
        record, checks = _verify_update(target, latest[target_key(target)], detection_by_pair[(target["task_id"], target["method"])], bench, repository_root, evidence)
        indexed = result_view["targets"][target_key(target)]
        record.update({"target_id": indexed["target_id"], "ledger_event": indexed["ledger_event"], "seal": indexed["seal"]})
        update_records.append(record)
        audit_targets.append({"target": target_key(target), "stage": "update", "status": "PASS", "checks": checks})
    evaluation_ready = False
    if update_targets:
        evaluation = evidence.json(run_root / "evaluation-dispatch.json")
        expected_update_keys = {target_key(target) for target in update_targets}
        ready_keys = {item.get("target") for item in evaluation.get("targets", []) if item.get("ready") is True}
        if evaluation.get("status") != "READY" or evaluation.get("evaluation_dispatched") is not False or ready_keys != expected_update_keys:
            raise ReportingError("EVALUATION_READINESS_INVALID", "Evaluation readiness evidence differs from sealed Update universe")
        evaluation_ready = True
    target_map = {target_key(target): target for target in targets}
    failures = [_classify_failure(target_map[target_key({
        "task_id": event["target"]["task_id"], "method": event["target"]["method"], "stage": event["target"]["stage"],
        "run_id": event["target"]["run_id"], "mode": event["target"]["update_mode"],
    })], event, repository_root, evidence) for event in events if event.get("state") == "FAILED"]
    failure_counts = Counter(item["classification"] for item in failures)
    failure_stage_counts = Counter(item["stage"] for item in failures)
    aggregates = _aggregates(detect_records, update_records, failures, classifications)
    legacy_updates = sum(item["sdd_artifacts_status"] == "NOT_CAPTURED_BY_V1_RUNNER" for item in update_records)
    report = {
        "schema_version": 2, "report_type": "BATCH_FINAL_OPERATIONAL_REPORT", "batch_id": config["batch_id"],
        "result_view_sha256": result_view["view_sha256"], "status": "PASS_WITH_LIMITATIONS",
        "semantics": {
            "operational_metrics_only": True, "correctness_assessed": False, "gold_agreement_assessed": False,
            "project_tests_run": False, "evaluation_ready": evaluation_ready, "evaluation_dispatched": False,
        },
        "counts": {
            "configured_targets": len(targets), "terminal_sealed_targets": len(targets),
            "detect_configured": len(detect_targets), "detect_sealed": len(detect_records),
            "update_configured": len(update_targets), "update_sealed": len(update_records),
            "sealed_detect_updates": sum(item["mode"] == "sealed-detect" for item in update_targets),
            "self_directed_updates": sum(item["mode"] == "self-directed" for item in update_targets), "historical_failed_events": len(failures),
            "historical_detect_failures": failure_stage_counts["detect"], "historical_update_failures": failure_stage_counts["update"],
            "final_scope_violations": sum(item["scope_violation_count"] for item in update_records),
        },
        "detect_targets": detect_records, "update_targets": update_records, "aggregates": aggregates,
        "failures": {"taxonomy": list(FAILURE_CLASSES), "counts": {name: failure_counts[name] for name in FAILURE_CLASSES}, "events": failures},
        "limitations": [
            {"code": "UPDATE_WORKSPACE_EXCLUDED_FROM_V1_SEAL", "status": "DISCLOSED", "affected_targets": legacy_updates},
            {"code": "UPDATE_SDD_ARTIFACTS_NOT_CAPTURED_BY_V1_RUNNER", "status": "DISCLOSED", "affected_targets": legacy_updates},
        ],
        "disclosures": {
            "execution_agent_gold_access": "NONE", "report_generator_gold_access": "NONE_BY_CONSTRUCTION",
            "host_continuation_session_gold_access": "ACCIDENTAL_READ_NOT_USED_IN_REPORT_OR_EXECUTION",
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    audit = {
        "schema_version": 1, "audit_type": "BATCH_FINAL_AUDIT", "batch_id": config["batch_id"],
        "status": "PASS_WITH_LIMITATIONS",
        "checks": [
            {"id": "configured-target-universe", "status": "PASS"}, {"id": "ledger-schema-sequence-hash-chain", "status": "PASS"},
            {"id": "global-detect-barrier", "status": "PASS"}, {"id": "all-detect-bundles", "status": "PASS"},
            {"id": "all-update-bundles", "status": "PASS"}, {"id": "tests-only-and-candidate-scope", "status": "PASS"},
            {"id": "self-directed-detect-isolation", "status": "PASS"}, {"id": "evaluation-ready-not-dispatched", "status": "PASS"},
            {"id": "project-tests-not-run", "status": "PASS"}, {"id": "legacy-update-sdd-artifact-capture", "status": "LIMITATION"},
        ],
        "ledger": {"event_count": len(events), "sha256": ledger_before, "chain_tip_sha256": events[-1]["event_sha256"] if events else None},
        "barrier_sha256": barrier["barrier_sha256"], "targets": audit_targets,
        "limitations": report["limitations"], "disclosures": report["disclosures"], "report_sha256": report["report_sha256"],
    }
    audit["audit_sha256"] = canonical_sha256(audit)
    source_files = sorted(evidence.files.values(), key=lambda item: item["path"])
    report_bytes = _json_bytes(report)
    audit_bytes = _json_bytes(audit)
    output_files = [
        {"path": f"sdd-bench/scrapy-sdd/batch/runs/{config['batch_id']}/final/report.json", "size_bytes": len(report_bytes), "sha256": hashlib.sha256(report_bytes).hexdigest()},
        {"path": f"sdd-bench/scrapy-sdd/batch/runs/{config['batch_id']}/final/audit.json", "size_bytes": len(audit_bytes), "sha256": hashlib.sha256(audit_bytes).hexdigest()},
    ]
    manifest = {
        "schema_version": 1, "manifest_type": "BATCH_FINAL_EVIDENCE_MANIFEST", "batch_id": config["batch_id"],
        "source_files": source_files, "source_file_count": len(source_files), "source_files_sha256": canonical_sha256(source_files),
        "output_files": output_files, "output_file_count": len(output_files), "output_files_sha256": canonical_sha256(output_files),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    _validate(report, bench / "schemas/batch-final-report-v2.schema.json", "FINAL_REPORT_SCHEMA_INVALID")
    _validate(audit, bench / "schemas/batch-final-audit-v1.schema.json", "FINAL_AUDIT_SCHEMA_INVALID")
    _validate(manifest, bench / "schemas/batch-evidence-manifest-v1.schema.json", "EVIDENCE_MANIFEST_SCHEMA_INVALID")
    if sha256_file(ledger_path) != ledger_before:
        raise ReportingError("LEDGER_MUTATED", "Ledger changed during read-only report generation")
    publication = _publish(run_root / "final", {"report.json": report, "audit.json": audit, "evidence-manifest.json": manifest})
    if sha256_file(ledger_path) != ledger_before:
        raise ReportingError("LEDGER_MUTATED", "Ledger changed during final publication")
    return {
        "schema_version": 1, "batch_id": config["batch_id"], "status": "READY",
        "audit_status": "PASS_WITH_LIMITATIONS", "publication": publication,
        "final_path": (run_root / "final").relative_to(repository_root).as_posix(),
        "evaluation_dispatched": False, "project_tests_run": False,
    }
