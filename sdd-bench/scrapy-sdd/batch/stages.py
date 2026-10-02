"""Fail-closed Detect and policy-bound Update stage launchers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .core import BatchError, canonical_sha256, display_path, sha256_file, write_json
from .scaffold import METHODS, prepare_codex_mountpoint as _prepare_codex_mountpoint


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate(value: dict[str, Any], schema: Path, code: str) -> None:
    validator = Draft202012Validator(
        json.loads(schema.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise BatchError(code, "JSON document failed schema", errors=[error.message for error in errors])


def _safe_id(value: str, label: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise BatchError("INVALID_IDENTIFIER", f"{label} is invalid", value=value)
    return value


def _safe_test_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in value
        and "//" not in value
        and bool(path.parts)
        and path.parts[0] in {"test", "tests", "testing"}
    )


def _task_context(task_manifest_path: Path, bench: Path) -> tuple[dict[str, Any], Path, str]:
    if task_manifest_path.is_symlink() or not task_manifest_path.is_file():
        raise BatchError("INVALID_TASK_MANIFEST", "Task manifest must be a regular non-symlink file")
    task = json.loads(task_manifest_path.read_text(encoding="utf-8"))
    _validate(task, bench / "schemas/task-v1.schema.json", "TASK_SCHEMA_INVALID")
    task_root = task_manifest_path.resolve().parent
    if task_root.name != task["task_id"]:
        raise BatchError("TASK_PATH_MISMATCH", "Task ID does not match task directory")
    base = task["baseline"]["base_sha"]
    lock = json.loads((bench / "batch/baselines" / base / "baseline-lock.json").read_text())
    if lock.get("base_sha") != base:
        raise BatchError("BASELINE_LOCK_MISMATCH", "Baseline lock does not match task")
    return task, task_root, base


def _artifact(path: Path, repository_root: Path) -> dict[str, str]:
    return {"path": display_path(path, repository_root), "sha256": sha256_file(path)}


def _file_manifest(root: Path) -> tuple[list[dict[str, Any]], str]:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            entries.append({
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return entries, canonical_sha256(entries)


def _capture_update_sdd_artifacts(
    *,
    workspace: Path,
    execution: Path,
    task: dict[str, Any],
    method: str,
    run_id: str,
    mode: str,
    bench: Path,
) -> tuple[Path, dict[str, Any]]:
    """Copy the method-owned Update planning tree into the sealed bundle."""
    relative_source = PurePosixPath(METHODS[method]["planning_workspace_path"])
    if relative_source.is_absolute() or ".." in relative_source.parts:
        raise BatchError(
            "INVALID_SDD_ARTIFACT_PATH",
            "Method planning path must remain inside the Update workspace",
        )
    source = workspace.joinpath(*relative_source.parts)
    if source.is_symlink() or not source.is_dir():
        raise BatchError(
            "INVALID_SDD_ARTIFACT_SOURCE",
            "Update planning artifact source must be a real directory",
        )
    destination = execution / "sdd-artifacts"
    if destination.exists() or destination.is_symlink():
        raise BatchError(
            "SDD_ARTIFACT_DESTINATION_EXISTS",
            "Refusing to overwrite captured Update planning artifacts",
        )
    destination.mkdir()
    files: list[dict[str, Any]] = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise BatchError(
                "SDD_ARTIFACT_SYMLINK",
                "Update planning artifacts may not contain symlinks",
                path=relative.as_posix(),
            )
        if path.is_dir():
            (destination / relative).mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            raise BatchError(
                "SDD_ARTIFACT_SPECIAL_FILE",
                "Update planning artifacts may contain only regular files and directories",
                path=relative.as_posix(),
            )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        files.append({
            "path": relative.as_posix(),
            "size_bytes": target.stat().st_size,
            "sha256": sha256_file(target),
        })
    manifest = {
        "schema_version": 1,
        "capture_type": "UPDATE_SDD_ARTIFACTS",
        "task_id": task["task_id"],
        "method": method,
        "run_id": run_id,
        "update_mode": mode,
        "status": "CAPTURED_NONEMPTY" if files else "CAPTURED_EMPTY",
        "source_workspace_path": relative_source.as_posix().rstrip("/"),
        "files": files,
        "file_count": len(files),
        "files_manifest_sha256": canonical_sha256(files),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    _validate(
        manifest,
        bench / "schemas/update-sdd-artifacts-v1.schema.json",
        "UPDATE_SDD_ARTIFACTS_SCHEMA_INVALID",
    )
    manifest_path = execution / "sdd-artifacts-manifest.json"
    write_json(manifest_path, manifest, refuse_overwrite=True)
    return manifest_path, manifest


def _workspace_content_sha256(root: Path) -> str:
    """Reproduce scaffold's immutable initial-workspace content digest."""
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts or not (path.is_file() or path.is_symlink()):
            continue
        data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        entries.append({
            "path": relative.as_posix(), "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return canonical_sha256(entries)


def _verify_initial_detect_workspace(task_root: Path, method: str, workspace: Path) -> None:
    lock = json.loads((task_root / "initial-workspaces.json").read_text(encoding="utf-8"))
    matches = [item for item in lock.get("workspaces", []) if item.get("method") == method]
    if len(matches) != 1 or _workspace_content_sha256(workspace) != matches[0].get("initial_workspace_sha256"):
        raise BatchError(
            "DETECT_CODE_MODIFIED",
            "Detect workspace differs from its frozen initial workspace; refusing to seal",
        )


def _read_detection_draft(execution: Path, planning_source: Path) -> tuple[dict[str, Any], Path]:
    """Locate exactly one Agent-authored draft in an explicitly writable Detect output."""
    direct = execution / "detection-draft.json"
    if direct.is_file() and not direct.is_symlink():
        candidates = [direct]
    else:
        candidates = [
            path for path in planning_source.rglob("detection-draft.json")
            if path.is_file() and not path.is_symlink()
        ]
    if len(candidates) != 1:
        raise BatchError(
            "DETECTION_DRAFT_CARDINALITY",
            "Exactly one regular detection-draft.json is required in the allowed Detect outputs",
            count=len(candidates),
        )
    path = candidates[0]
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchError("INVALID_DETECTION_DRAFT", "Detection draft is not valid JSON") from exc
    return draft, path


def _agent_turn_completed(agent_log: Path) -> bool:
    if agent_log.is_symlink() or not agent_log.is_file():
        return False
    for line in agent_log.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            return True
    return False


def _make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            try:
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
            except FileNotFoundError:
                pass


def _make_read_only(root: Path) -> None:
    for path in [*root.rglob("*"), root]:
        if not path.is_symlink():
            try:
                path.chmod(path.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
            except FileNotFoundError:
                pass


def _copy_initialization(task_root: Path, method: str, workspace: Path) -> None:
    source = task_root / "initialization" / method / "files"
    for path in source.rglob("*"):
        if path.is_file():
            target = workspace / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)


def _canonical_policy_valid(policy: dict[str, Any]) -> bool:
    supplied = policy.get("policy_sha256")
    payload = dict(policy)
    payload.pop("policy_sha256", None)
    return isinstance(supplied, str) and canonical_sha256(payload) == supplied


def validate_update_policy(
    *,
    task_manifest: Path,
    policy_path: Path,
    bench: Path,
    method: str | None = None,
    run_id: str | None = None,
    expected_file_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path, str]:
    task, task_root, base = _task_context(task_manifest, bench)
    if policy_path.is_symlink() or not policy_path.is_file():
        raise BatchError("INVALID_UPDATE_POLICY", "Policy must be a regular non-symlink file")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    _validate(policy, bench / "schemas/update-policy-v1.schema.json", "UPDATE_POLICY_SCHEMA_INVALID")
    if not _canonical_policy_valid(policy):
        raise BatchError("UPDATE_POLICY_PAYLOAD_HASH_MISMATCH", "Policy canonical hash is invalid")
    actual_file_sha = sha256_file(policy_path)
    sidecar = policy_path.with_name("update-policy.sha256")
    if sidecar.is_symlink() or not sidecar.is_file():
        raise BatchError("UPDATE_POLICY_HASH_LOCK_MISSING", "Policy SHA-256 sidecar is required")
    parts = sidecar.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[1] != "update-policy.json" or parts[0] != actual_file_sha:
        raise BatchError("UPDATE_POLICY_FILE_HASH_MISMATCH", "Policy file differs from immutable sidecar")
    if expected_file_sha256 is not None and expected_file_sha256 != actual_file_sha:
        raise BatchError("BATCH_POLICY_HASH_MISMATCH", "Batch config policy SHA-256 differs")
    checks = {
        "task": policy["task_id"] == task["task_id"],
        "task_sha": policy["task_manifest_sha256"] == sha256_file(task_manifest),
        "base": policy["base_sha"] == base,
        "method": method is None or policy["method"] == method,
        "run": run_id is None or policy["run_id"] == run_id,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BatchError("UPDATE_POLICY_CONTEXT_MISMATCH", "Policy does not belong to this execution", failed=failed)
    expected_dir = task_root / "runs" / policy["method"] / "update" / "policies" / policy["run_id"]
    if policy_path.resolve().parent != expected_dir.resolve():
        raise BatchError("CROSS_TASK_POLICY_PATH", "Policy is outside its canonical task/method/run directory")
    if policy["mode"] == "self-directed":
        override = Path(policy["compose"]["override_path"])
        if not override.is_absolute():
            override = bench.parents[1] / override
        if not override.is_file() or sha256_file(override) != policy["compose"]["override_sha256"]:
            raise BatchError("UPDATE_OVERRIDE_HASH_MISMATCH", "Self-directed Compose override changed")
    return policy, task, task_root, actual_file_sha


def validate_detection_prerequisite(
    *, task: dict[str, Any], task_root: Path, method: str, bench: Path
) -> tuple[dict[str, Any], Path, str]:
    manifest_path = task_root / "runs" / method / "update/sealed-input/detection-manifest.json"
    planning = task_root / "runs" / method / "update/sealed-input/planning-artifacts"
    if not manifest_path.is_file() or not planning.is_dir():
        raise BatchError("DETECT_NOT_SEALED", "Formal Detect seal is missing", method=method)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate(manifest, bench / "schemas/detection-v1.schema.json", "DETECTION_SCHEMA_INVALID")
    payload = dict(manifest)
    seal = payload.pop("seal")
    if seal["payload_sha256"] != canonical_sha256(payload):
        raise BatchError("DETECTION_SEAL_MISMATCH", "Detection manifest seal is invalid")
    if (
        manifest["producer"]["kind"] != "agent"
        or manifest["task_id"] != task["task_id"]
        or manifest["method"] != method
        or manifest["base_sha"] != task["baseline"]["base_sha"]
        or manifest["task_input_sha256"] != sha256_file(task_root / "experiment-inputs/task.md")
    ):
        raise BatchError("DETECTION_CONTEXT_MISMATCH", "Detection manifest provenance mismatch")
    _, planning_sha = _file_manifest(planning)
    if manifest["planning_artifacts"]["manifest_sha256"] != planning_sha:
        raise BatchError("PLANNING_SEAL_MISMATCH", "Sealed planning artifacts changed")
    return manifest, manifest_path, sha256_file(manifest_path)


def _preflight_ready(task_root: Path, method: str, stage: str) -> None:
    path = task_root / "runs" / method / stage / "preflight/preflight-report.json"
    if not path.is_file():
        raise BatchError("PREFLIGHT_MISSING", "Stage preflight report is missing")
    report = json.loads(path.read_text(encoding="utf-8"))
    if stage == "detect":
        ready = report.get("status") == "READY" and report.get("formal_run_permitted") is True
    else:
        ready = report.get("security", {}).get("bubblewrap_pass") is True and all(
            report.get("mounts", {}).get(key) is True
            for key in ("docker_socket_absent", "host_gold_absent", "raw_dataset_absent")
        )
    if not ready:
        raise BatchError("PREFLIGHT_NOT_READY", "Stage preflight boundary is not ready")


def _checkpoint(
    *,
    task: dict[str, Any], method: str, stage: str, run_id: str, mode: str | None,
    status: str, dry_run: bool, model_request: bool, task_sha: str,
    policy_sha: str | None, detection_sha: str | None, rendered_sha: str | None,
    checks: list[tuple[str, bool]], artifacts: list[dict[str, str]], blockers: list[str],
    bench: Path,
) -> dict[str, Any]:
    value = {
        "schema_version": 1, "task_id": task["task_id"], "method": method, "stage": stage,
        "run_id": run_id, "update_mode": mode, "base_sha": task["baseline"]["base_sha"],
        "created_at_utc": _now(), "status": status, "dry_run": dry_run,
        "tests_run": False, "model_request_sent": model_request,
        "provenance": {
            "task_manifest_sha256": task_sha, "policy_file_sha256": policy_sha,
            "detection_manifest_sha256": detection_sha, "compose_rendered_sha256": rendered_sha,
        },
        "checks": [{"id": name, "status": "PASS" if passed else "FAIL"} for name, passed in checks],
        "artifacts": artifacts, "blockers": blockers,
    }
    _validate(value, bench / "schemas/stage-execution-v1.schema.json", "EXECUTION_SCHEMA_INVALID")
    return value


def _codex_catalog_override(method: str, stage: str, runtime: Path) -> str:
    """Render the per-attempt Codex mountpoint and audited model catalog."""
    return (
        f"services:\n  {method}-{stage}-agent:\n"
        "    tmpfs:\n"
        "      - /workspace/.codex:rw,nosuid,nodev,noexec,mode=0700,uid=1007,gid=1007,size=1m\n"
        "    volumes:\n"
        f"      - type: bind\n        source: {runtime / 'model-catalogs/deepseek-flash/models.json'}\n"
        "        target: /home/bench/.codex/model-catalogs/deepseek-flash/models.json\n"
        "        read_only: true\n        bind:\n          create_host_path: false\n"
    )


def _run_compose_agent(
    *, task_root: Path, bench: Path, method: str, stage: str, run_id: str, mode: str | None,
    env: dict[str, str], prompt: str, output: Path, override: Path | None,
) -> tuple[str, str]:
    compose_files = ["-f", str(task_root / "compose.yaml")]
    if override:
        compose_files += ["-f", str(override)]
    # The pinned DeepSeek profile's model catalog path is /home/bench/... .
    # Formal containers use a fresh /run/sdd-home HOME, so expose the same
    # already-audited catalog at the profile's absolute path as read-only.
    runtime = bench / "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates"
    catalog = runtime / "model-catalogs/deepseek-flash/models.json"
    if catalog.is_symlink() or not catalog.is_file():
        raise BatchError("MODEL_CATALOG_MISSING", "Pinned model catalog is missing", path=str(catalog))
    catalog_override = output / "codex-catalog.override.yaml"
    catalog_override.write_text(
        _codex_catalog_override(method, stage, runtime),
        encoding="utf-8",
    )
    compose_files += ["-f", str(catalog_override)]
    profile = f"{method}-{stage}"
    project = f"{task_root.name.replace('__', '-')}-{method}-{stage}-{mode or 'detect'}-{run_id}"
    base = ["docker", "compose", *compose_files, "--profile", profile, "--project-name", project]
    proxy = f"{method}-{stage}-proxy"
    agent = f"{method}-{stage}-agent"
    rendered = subprocess.run(
        base + ["config", agent, proxy], cwd=task_root, env=env, check=True,
        text=True, stdout=subprocess.PIPE,
    ).stdout
    rendered_path = output / "rendered-compose.yaml"
    rendered_path.write_text(rendered, encoding="utf-8")
    rendered_sha = sha256_file(rendered_path)
    subprocess.run(base + ["up", "-d", "--wait", "--wait-timeout", "120", proxy], cwd=task_root, env=env, check=True)
    try:
        launch = (
            "set -eu; "
            "export CODEX_HOME=/run/sdd-home/.codex-run; "
            "mkdir -p \"$CODEX_HOME/model-catalogs/deepseek-flash\"; "
            "cp /run/sdd-home/.codex/config.toml \"$CODEX_HOME/config.toml\"; "
            "cp /run/sdd-home/.codex/deepseek-flash.config.toml \"$CODEX_HOME/deepseek-flash.config.toml\"; "
            "cp /run/sdd-home/.codex/model-catalogs/deepseek-flash/models.json "
            "\"$CODEX_HOME/model-catalogs/deepseek-flash/models.json\"; "
            "exec timeout --foreground --signal=TERM --kill-after=30s 2700s "
            "codex exec --strict-config --profile deepseek-flash --ephemeral --json "
            "--color never -C /workspace -"
        )
        result = subprocess.run(
            base + ["run", "--no-deps", agent, "/bin/sh", "-c", launch],
            cwd=task_root, env=env, input=prompt, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        (output / "agent.jsonl").write_text(result.stdout, encoding="utf-8")
        (output / "agent.stderr.log").write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            raise BatchError("AGENT_RUN_FAILED", "Formal Agent process failed", returncode=result.returncode)
        return hashlib.sha256(result.stdout.encode()).hexdigest(), rendered_sha
    finally:
        subprocess.run(base + ["down", "-v", "--remove-orphans"], cwd=task_root, env=env, check=False)


def detect_targets(
    *, task_manifest: Path, method: str, run_id: str, output: Path, bench: Path,
    repository_root: Path, dry_run: bool, recover_existing: bool = False,
) -> dict[str, Any]:
    _safe_id(run_id, "run_id")
    if method not in METHODS:
        raise BatchError("INVALID_METHOD", "Unknown SDD method")
    task, task_root, base = _task_context(task_manifest, bench)
    _preflight_ready(task_root, method, "detect")
    task_sha = sha256_file(task_manifest)
    checks = [("task-schema", True), ("recorded-base", True), ("detect-preflight", True)]
    if dry_run:
        return _checkpoint(
            task=task, method=method, stage="detect", run_id=run_id, mode=None,
            status="DRY_RUN_READY", dry_run=True, model_request=False, task_sha=task_sha,
            policy_sha=None, detection_sha=None, rendered_sha=None, checks=checks,
            artifacts=[], blockers=[], bench=bench,
        )
    execution = output.resolve()
    expected_parent = task_root / "runs" / method / "detect" / "executions"
    try:
        execution.relative_to(expected_parent.resolve())
    except ValueError as exc:
        raise BatchError("INVALID_DETECT_OUTPUT", "Detect output must be inside its task/method executions") from exc
    if execution.exists() and not recover_existing:
        raise BatchError("RUN_ID_ALREADY_EXISTS", "Detect execution output already exists")
    if recover_existing:
        if not execution.is_dir():
            raise BatchError("RECOVERY_OUTPUT_MISSING", "Detect recovery output does not exist")
    else:
        execution.mkdir(parents=True)
    detect_workspace = task_root / "runs" / method / "detect" / "workspace"
    workspace_before = _workspace_snapshot(detect_workspace)
    planning_source = task_root / "runs" / method / "detect/planning-artifacts"
    if recover_existing:
        agent_log = execution / "agent.jsonl"
        rendered_path = execution / "rendered-compose.yaml"
        if not _agent_turn_completed(agent_log) or rendered_path.is_symlink() or not rendered_path.is_file():
            raise BatchError(
                "DETECT_RECOVERY_NOT_ELIGIBLE",
                "Recovery requires an existing completed Agent session and rendered Compose evidence",
            )
        _verify_initial_detect_workspace(task_root, method, detect_workspace)
        session_sha, rendered_sha = sha256_file(agent_log), sha256_file(rendered_path)
    else:
        env = dict(os.environ)
        upper = method.upper().replace("-", "_")
        env.update({
            "COMPOSE_PROJECT_NAME": f"{task_root.name}-{method}-detect-{run_id}",
            "DEEPSEEK_API_KEY_FILE": str(Path.home() / ".config/sdd-bench/deepseek-api-key"),
            f"{upper}_DETECT_WORKSPACE": str(task_root / "runs" / method / "detect/workspace"),
            f"{upper}_DETECT_OUTPUT": str(execution),
            f"{upper}_DETECT_PLANNING": str(planning_source),
            "PREFLIGHT_TASK_INPUT": str(task_root / "experiment-inputs"),
        })
        phases = ", ".join(METHODS[method]["detect_phases"])
        prompt = (
            f"Perform only the {method} Detect planning phases ({phases}). Read /task-input/task.md. "
            "Do not run tests and do not modify project code or tests. Locate candidate test files. "
            "Write exactly one detection-draft.json inside the mounted method planning directory; "
            "it must contain only a candidates array, and each candidate has path, symbols, and reason. "
            "Paths must be repository-relative test paths. Write all other method planning artifacts "
            "only in that same mounted planning directory."
        )
        session_sha, rendered_sha = _run_compose_agent(
            task_root=task_root, bench=bench, method=method, stage="detect", run_id=run_id, mode=None,
            env=env, prompt=prompt, output=execution, override=None,
        )
    workspace_after = _workspace_snapshot(detect_workspace)
    if workspace_after != workspace_before:
        changed = _changed_paths(workspace_before, workspace_after)
        raise BatchError(
            "DETECT_CODE_MODIFIED", "Detect changed project files; refusing to seal",
            changed_paths=changed,
        )
    draft, draft_path = _read_detection_draft(execution, planning_source)
    if set(draft) != {"candidates"} or not isinstance(draft["candidates"], list):
        raise BatchError("INVALID_DETECTION_DRAFT", "Detection draft has unknown or missing fields")
    for candidate in draft["candidates"]:
        if (
            not isinstance(candidate, dict)
            or set(candidate) != {"path", "symbols", "reason"}
            or not _safe_test_path(candidate.get("path", ""))
            or not isinstance(candidate.get("symbols"), list)
            or not isinstance(candidate.get("reason"), str)
            or not candidate["reason"]
        ):
            raise BatchError("INVALID_DETECTION_CANDIDATE", "Detection candidate is invalid")
    sealed_root = task_root / "runs" / method / "update/sealed-input"
    if sealed_root.exists():
        raise BatchError("DETECTION_ALREADY_SEALED", "Refusing to overwrite Detect seal")
    planning_target = sealed_root / "planning-artifacts"
    sealed_root.mkdir(parents=True)
    shutil.copytree(planning_source, planning_target)
    entries, planning_sha = _file_manifest(planning_target)
    payload = {
        "schema_version": 1, "manifest_type": "SEALED_DETECTION", "task_id": task["task_id"],
        "method": method, "base_sha": base,
        "producer": {"kind": "agent", "stage": "detect", "run_id": run_id, "session_sha256": session_sha},
        "task_input_sha256": sha256_file(task_root / "experiment-inputs/task.md"),
        "candidates": draft["candidates"],
        "planning_artifacts": {"file_count": len(entries), "manifest_sha256": planning_sha},
    }
    manifest = {**payload, "seal": {
        "algorithm": "sha256-canonical-json-without-seal", "payload_sha256": canonical_sha256(payload)
    }}
    _validate(manifest, bench / "schemas/detection-v1.schema.json", "DETECTION_SCHEMA_INVALID")
    manifest_path = sealed_root / "detection-manifest.json"
    write_json(manifest_path, manifest, refuse_overwrite=True)
    shutil.copyfile(manifest_path, execution / "detection-manifest.json")
    shutil.copytree(planning_target, execution / "sdd-artifacts")
    detect_summary = {
        "schema_version": 1, "task_id": task["task_id"], "method": method,
        "detect_run_id": run_id, "base_sha": base, "status": "SEALED",
        "project_code_changed": False, "tests_run": False,
        "candidate_test_file_count": len({item["path"] for item in draft["candidates"]}),
        "detection_manifest_sha256": sha256_file(manifest_path),
        "planning_artifacts_sha256": planning_sha,
        "task_manifest_sha256": task_sha,
    }
    detect_summary["summary_sha256"] = canonical_sha256(detect_summary)
    write_json(execution / "detect-summary.json", detect_summary, refuse_overwrite=True)
    if draft_path != execution / "detection-draft.json":
        shutil.copyfile(draft_path, execution / "detection-draft.json")
    _make_read_only(sealed_root)
    checkpoint = _checkpoint(
        task=task, method=method, stage="detect", run_id=run_id, mode=None, status="SEALED",
        dry_run=False, model_request=True, task_sha=task_sha, policy_sha=None,
        detection_sha=sha256_file(manifest_path), rendered_sha=rendered_sha, checks=checks,
        artifacts=[_artifact(manifest_path, repository_root)], blockers=[], bench=bench,
    )
    write_json(execution / "checkpoint.json", checkpoint, refuse_overwrite=True)
    bundle_files, bundle_sha = _file_manifest(execution)
    seal = {
        "schema_version": 1, "seal_type": "IMMUTABLE_DETECTION_BUNDLE",
        "task_id": task["task_id"], "method": method, "run_id": run_id,
        "base_sha": base, "file_count": len(bundle_files),
        "files_manifest_sha256": bundle_sha,
    }
    seal["seal_sha256"] = canonical_sha256(seal)
    write_json(execution / "seal.json", seal, refuse_overwrite=True)
    _make_read_only(execution)
    return checkpoint


def _workspace_snapshot(workspace: Path) -> dict[str, str]:
    snapshot = {}
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace)
        if ".git" in relative.parts or not path.is_file() or path.is_symlink():
            continue
        snapshot[relative.as_posix()] = sha256_file(path)
    return snapshot


def _changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def enforce_update_scope(mode: str, changed_paths: list[str], candidates: list[str]) -> list[str]:
    violations = [path for path in changed_paths if not _safe_test_path(path)]
    if mode == "sealed-detect":
        allowed = set(candidates)
        violations.extend(path for path in changed_paths if path not in allowed)
    return sorted(set(violations))


def update_tests(
    *, task_manifest: Path, policy_path: Path, output: Path, bench: Path,
    repository_root: Path, dry_run: bool, expected_policy_sha256: str | None = None,
) -> dict[str, Any]:
    policy, task, task_root, policy_file_sha = validate_update_policy(
        task_manifest=task_manifest, policy_path=policy_path, bench=bench,
        expected_file_sha256=expected_policy_sha256,
    )
    method, run_id, mode = policy["method"], policy["run_id"], policy["mode"]
    _preflight_ready(task_root, method, "update")
    detection, detection_path, detection_sha = validate_detection_prerequisite(
        task=task, task_root=task_root, method=method, bench=bench
    )
    checks = [
        ("policy-schema", True), ("policy-file-hash", True), ("policy-context", True),
        ("detect-prerequisite", True), ("update-preflight", True),
        ("mode-explicit", True), ("tests-only-policy", True),
    ]
    task_sha = sha256_file(task_manifest)
    if dry_run:
        return _checkpoint(
            task=task, method=method, stage="update", run_id=run_id, mode=mode,
            status="DRY_RUN_READY", dry_run=True, model_request=False, task_sha=task_sha,
            policy_sha=policy_file_sha, detection_sha=detection_sha, rendered_sha=None,
            checks=checks, artifacts=[], blockers=[], bench=bench,
        )
    execution = output.resolve() / f"mode-{mode}"
    expected_parent = task_root / "runs" / method / "update" / "executions"
    try:
        execution.relative_to(expected_parent.resolve())
    except ValueError as exc:
        raise BatchError("INVALID_UPDATE_OUTPUT", "Update output must be inside its task/method executions") from exc
    if execution.exists():
        raise BatchError("RUN_ID_ALREADY_EXISTS", "Update execution output already exists")
    workspace = execution / "workspace"
    artifacts_dir = execution / "artifacts"
    execution.mkdir(parents=True)
    artifacts_dir.mkdir()
    base = task["baseline"]["base_sha"]
    shutil.copytree(bench / "batch/baselines" / base / "repository", workspace, symlinks=True)
    _make_writable(workspace)
    _copy_initialization(task_root, method, workspace)
    _prepare_codex_mountpoint(workspace)
    (workspace / METHODS[method]["planning_workspace_path"]).mkdir(parents=True, exist_ok=True)
    initial_snapshot = _workspace_snapshot(workspace)
    upper = method.upper().replace("-", "_")
    env = dict(os.environ)
    env.update({
        "COMPOSE_PROJECT_NAME": f"{task_root.name}-{method}-update-{mode}-{run_id}",
        "DEEPSEEK_API_KEY_FILE": str(Path.home() / ".config/sdd-bench/deepseek-api-key"),
        f"{upper}_UPDATE_WORKSPACE": str(workspace), f"{upper}_UPDATE_TESTS": str(workspace / "tests"),
        f"{upper}_UPDATE_OUTPUT": str(artifacts_dir),
        "PREFLIGHT_TASK_INPUT": str(task_root / "experiment-inputs"),
        "UPDATE_TASK_INPUT": str(task_root / "experiment-inputs"),
        "UPDATE_POLICY_FILE": str(policy_path.resolve()),
    })
    override: Path | None = None
    if mode == "sealed-detect":
        sealed = task_root / "runs" / method / "update/sealed-input"
        env.update({
            f"{upper}_UPDATE_SEALED_PLANNING": str(sealed / "planning-artifacts"),
            f"{upper}_UPDATE_DETECTION": str(detection_path),
            f"{upper}_UPDATE_DETECTION_TARGET": "/input/detection-manifest.json",
        })
        policy_override = execution / "policy-mount.override.yaml"
        policy_override.write_text(
            f"services:\n  {method}-update-agent:\n    environment:\n"
            f"      UPDATE_TARGET_POLICY: sealed-detect\n    volumes:\n"
            f"      - type: bind\n        source: {policy_path.resolve()}\n"
            f"        target: /run/sdd-policy/update-policy.json\n        read_only: true\n"
            f"        bind:\n          create_host_path: false\n",
            encoding="utf-8",
        )
        override = policy_override
    else:
        override = repository_root / policy["compose"]["override_path"]
    prompt = (
        "Perform only the Update implementation phase. Read /task-input/task.md and the immutable "
        "policy at /run/sdd-policy/update-policy.json. Do not run tests. Never modify production code "
        "or project configuration. Modify only tests/. "
    )
    if mode == "sealed-detect":
        prompt += (
            "Use only /input/detection-manifest.json and the mounted sealed planning artifacts to "
            "choose target files; do not modify test files outside the sealed candidate paths."
        )
    else:
        prompt += (
            "Independently locate which tests should change. No Detect manifest, planning artifact, "
            "workspace, HOME, cache, or session is available."
        )
    _, rendered_sha = _run_compose_agent(
        task_root=task_root, bench=bench, method=method, stage="update", run_id=run_id, mode=mode,
        env=env, prompt=prompt, output=artifacts_dir, override=override,
    )
    changed = _changed_paths(initial_snapshot, _workspace_snapshot(workspace))
    candidates = [item["path"] for item in detection["candidates"]]
    violations = enforce_update_scope(mode, changed, candidates)
    diff = subprocess.run(
        ["git", "-C", str(workspace), "diff", "--binary", "--", "tests"],
        check=True, text=True, stdout=subprocess.PIPE,
    ).stdout
    # `git diff` omits new untracked tests. Include them explicitly so the
    # sealed candidate patch contains the Agent's complete tests-only result.
    for path in changed:
        if not _safe_test_path(path) or not (workspace / path).is_file():
            continue
        tracked = subprocess.run(
            ["git", "-C", str(workspace), "ls-files", "--error-unmatch", "--", path],
            text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if tracked.returncode == 0:
            continue
        added = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "--", "/dev/null", path],
            cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if added.returncode not in {0, 1}:
            raise BatchError("CANDIDATE_PATCH_FAILED", "Could not record a new test file", path=path)
        diff += added.stdout
    diff_path = artifacts_dir / "candidate.patch"
    diff_path.write_text(diff, encoding="utf-8")
    status = "BLOCKED" if violations else "SEALED"
    blockers = ["out_of_scope_test_modification"] if violations else []
    scope_path = artifacts_dir / "scope-audit.json"
    write_json(scope_path, {
        "schema_version": 1, "mode": mode, "changed_paths": changed,
        "candidate_paths_sha256": canonical_sha256(sorted(candidates)),
        "violations": violations, "status": status,
    })
    modified_files = []
    final_snapshot = _workspace_snapshot(workspace)
    for path in changed:
        if not _safe_test_path(path):
            continue
        change_type = (
            "added" if path not in initial_snapshot else
            "deleted" if path not in final_snapshot else
            "modified"
        )
        modified_files.append({"path": path, "change_type": change_type})
    modified_manifest = {
        "schema_version": 1, "task_id": task["task_id"], "method": method,
        "update_run_id": run_id, "update_mode": mode, "base_sha": base,
        "detection_manifest_sha256": detection_sha,
        "update_policy_sha256": policy_file_sha,
        "candidate_modified_test_files": modified_files,
        "candidate_modified_test_file_count": len(modified_files),
    }
    modified_manifest["manifest_sha256"] = canonical_sha256(modified_manifest)
    modified_path = execution / "candidate-modified-files.json"
    write_json(modified_path, modified_manifest, refuse_overwrite=True)
    sdd_manifest_path, sdd_manifest = _capture_update_sdd_artifacts(
        workspace=workspace,
        execution=execution,
        task=task,
        method=method,
        run_id=run_id,
        mode=mode,
        bench=bench,
    )
    policy_reference = {
        "schema_version": 1, "task_id": task["task_id"], "method": method,
        "run_id": run_id, "mode": mode,
        "policy_path": display_path(policy_path, repository_root),
        "policy_sha256": policy_file_sha,
    }
    policy_reference["reference_sha256"] = canonical_sha256(policy_reference)
    write_json(execution / "policy-reference.json", policy_reference, refuse_overwrite=True)
    update_summary = {
        "schema_version": 1, "task_id": task["task_id"], "method": method,
        "update_run_id": run_id, "update_mode": mode, "base_sha": base,
        "status": status, "tests_run": False,
        "detection_visible_to_agent": mode == "sealed-detect",
        "sealed_planning_visible_to_agent": mode == "sealed-detect",
        "detection_manifest_sha256": detection_sha,
        "update_policy_sha256": policy_file_sha,
        "candidate_patch_sha256": sha256_file(diff_path),
        "candidate_modified_test_file_count": len(modified_files),
        "sdd_artifacts_status": sdd_manifest["status"],
        "sdd_artifacts_manifest_sha256": sha256_file(sdd_manifest_path),
        "violations": violations,
    }
    update_summary["summary_sha256"] = canonical_sha256(update_summary)
    write_json(execution / "update-summary.json", update_summary, refuse_overwrite=True)
    checkpoint = _checkpoint(
        task=task, method=method, stage="update", run_id=run_id, mode=mode, status=status,
        dry_run=False, model_request=True, task_sha=task_sha, policy_sha=policy_file_sha,
        detection_sha=detection_sha, rendered_sha=rendered_sha,
        checks=checks + [("post-run-scope", not violations)],
        artifacts=[
            _artifact(diff_path, repository_root),
            _artifact(scope_path, repository_root),
            _artifact(modified_path, repository_root),
            _artifact(sdd_manifest_path, repository_root),
        ],
        blockers=blockers, bench=bench,
    )
    write_json(execution / "checkpoint.json", checkpoint, refuse_overwrite=True)
    bundle_roots = [path for path in execution.iterdir() if path.name != "workspace"]
    bundle_entries = []
    for root in sorted(bundle_roots):
        if root.is_file():
            bundle_entries.append({"path": root.name, "sha256": sha256_file(root)})
        elif root.is_dir():
            entries, manifest_sha = _file_manifest(root)
            bundle_entries.append({"path": root.name + "/", "file_count": len(entries), "sha256": manifest_sha})
    update_seal = {
        "schema_version": 1, "seal_type": "IMMUTABLE_UPDATE_BUNDLE",
        "task_id": task["task_id"], "method": method, "run_id": run_id,
        "update_mode": mode, "base_sha": base,
        "bundle_manifest_sha256": canonical_sha256(bundle_entries),
        "entry_count": len(bundle_entries), "status": status,
    }
    update_seal["seal_sha256"] = canonical_sha256(update_seal)
    write_json(execution / "seal.json", update_seal, refuse_overwrite=True)
    _make_read_only(execution)
    return checkpoint
