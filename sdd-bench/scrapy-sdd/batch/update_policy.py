"""Record an explicit, fail-closed Update target-selection policy."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .core import BatchError, canonical_sha256, display_path, sha256_file, write_json

METHODS = ("openspec", "speckit", "cc-sdd")
MODES = ("sealed-detect", "self-directed")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise BatchError("INVALID_RUN_ID", "Run ID is not a safe identifier", run_id=value)
    return value


def _self_directed_override(task: Path, bench: Path, method: str) -> str:
    upper = method.upper().replace("-", "_")
    runtime = bench / "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates"
    service = f"{method}-update-agent"
    # !override is supported by the pinned Docker Compose and replaces, rather
    # than appends to, the sealed-detect volume list.
    return f"""services:
  {service}:
    environment:
      UPDATE_TARGET_POLICY: self-directed
    volumes: !override
      - type: bind
        source: ${{{upper}_UPDATE_WORKSPACE:-./runs/{method}/update/workspace}}
        target: /workspace
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: ${{{upper}_UPDATE_OUTPUT:-./runs/{method}/update/output}}
        target: /output
        read_only: false
        bind:
          create_host_path: false
      - type: bind
        source: ${{UPDATE_TASK_INPUT:-./experiment-inputs}}
        target: /task-input
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: {runtime / "config.toml"}
        target: /run/sdd-home/.codex/config.toml
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: {runtime / "deepseek-flash.config.toml"}
        target: /run/sdd-home/.codex/deepseek-flash.config.toml
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: {runtime / "model-catalogs/deepseek-flash/models.json"}
        target: /run/sdd-home/.codex/model-catalogs/deepseek-flash/models.json
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: ${{{upper}_UPDATE_TESTS:-./runs/{method}/update/workspace/tests}}
        target: /workspace/tests
        read_only: false
        bind:
          create_host_path: false
      - type: bind
        source: ${{UPDATE_POLICY_FILE:?immutable update policy is required}}
        target: /run/sdd-policy/update-policy.json
        read_only: true
        bind:
          create_host_path: false
"""


def select_update_policy(
    *,
    task: Path,
    bench: Path,
    repository_root: Path,
    method: str,
    mode: str,
    run_id: str,
) -> dict[str, Any]:
    task = task.resolve()
    run_id = _safe_id(run_id)
    if method not in METHODS:
        raise BatchError("INVALID_METHOD", "Unknown SDD method", method=method)
    if mode not in MODES:
        raise BatchError("INVALID_UPDATE_MODE", "Unknown Update target policy", mode=mode)
    if not (task / "task.json").is_file() or not (task / "compose.yaml").is_file():
        raise BatchError("TASK_NOT_DEPLOYED", "Task has no Prompt 7 Compose deployment", task=str(task))
    task_manifest = json.loads((task / "task.json").read_text(encoding="utf-8"))
    base_sha = task_manifest.get("baseline", {}).get("base_sha")
    if not isinstance(base_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        raise BatchError("INVALID_TASK_BASE", "Task manifest has no valid recorded base SHA")
    output = task / "runs" / method / "update" / "policies" / run_id
    if output.exists():
        raise BatchError("UPDATE_POLICY_ALREADY_EXISTS", "Refusing to overwrite frozen Update policy", path=str(output))
    output.mkdir(parents=True)
    override_path: Path | None = None
    override_sha: str | None = None
    if mode == "self-directed":
        override_path = output / "compose.self-directed.yaml"
        override_path.write_text(_self_directed_override(task, bench, method), encoding="utf-8")
        override_sha = sha256_file(override_path)
    visibility = mode == "sealed-detect"
    policy: dict[str, Any] = {
        "schema_version": 1,
        "policy_type": "UPDATE_TARGET_SELECTION",
        "task_id": task.name,
        "task_manifest_sha256": sha256_file(task / "task.json"),
        "base_sha": base_sha,
        "method": method,
        "stage": "update",
        "run_id": run_id,
        "mode": mode,
        "selected_at_utc": _now(),
        "detect_must_complete_first": True,
        "visibility": {
            "sealed_detection_manifest": visibility,
            "sealed_planning_artifacts": visibility,
            "other_detection_results": False,
            "detect_workspace": False,
            "task_title_body": True,
        },
        "filesystem": {
            "writable_directories": ["tests/"],
            "production_writable": False,
            "tests_writable": True,
        },
        "enforcement": {
            "target_source": "sealed-detection-candidates" if visibility else "agent-reasoning",
            "post_run_diff_rule": "subset-of-sealed-candidates" if visibility else "adapter-tests-only",
            "out_of_scope_result": "BLOCKED",
        },
        "compose": {
            "base_path": display_path(task / "compose.yaml", repository_root),
            "override_path": display_path(override_path, repository_root) if override_path else None,
            "override_sha256": override_sha,
        },
        "gold_blind": True,
        "selection_source": "explicit-user-cli",
    }
    policy["policy_sha256"] = canonical_sha256(policy)
    schema = json.loads((bench / "schemas/update-policy-v1.schema.json").read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy),
        key=lambda error: list(error.path),
    )
    if errors:
        raise BatchError("UPDATE_POLICY_SCHEMA_INVALID", "Update policy failed schema", errors=[error.message for error in errors])
    policy_path = output / "update-policy.json"
    write_json(policy_path, policy, refuse_overwrite=True)
    file_sha = sha256_file(policy_path)
    (output / "update-policy.sha256").write_text(
        f"{file_sha}  update-policy.json\n", encoding="utf-8"
    )
    return {
        "status": "SELECTED_AWAITING_DETECT_COMPLETION",
        "task_id": task.name,
        "method": method,
        "mode": mode,
        "run_id": run_id,
        "policy": display_path(policy_path, repository_root),
        "policy_sha256": file_sha,
        "formal_update_started": False,
    }
