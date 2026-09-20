"""Compile a pinned, concise experiment into a read-only prepared manifest.

No execution, ledger mutation, or historical artifact creation occurs here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .core import BatchError, canonical_sha256, sha256_file, write_json

BENCH = Path(__file__).resolve().parent.parent
ROOT = BENCH.parents[1]


def _validate(document: dict[str, Any], schema_name: str) -> None:
    schema = json.loads((BENCH / "schemas" / schema_name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: str(error.json_path))
    if errors:
        error = errors[0]
        raise BatchError("PREPARE_SCHEMA_INVALID", error.message, location=error.json_path)


def _pinned(root: Path, artifact: dict[str, str]) -> Path:
    relative = Path(artifact["path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in artifact["path"]:
        raise BatchError("PREPARE_PATH_INVALID", "Input path must remain in the repository", path=artifact["path"])
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise BatchError("PREPARE_INPUT_MISSING", "Pinned input is missing or unsafe", path=artifact["path"])
    if sha256_file(path) != artifact["sha256"]:
        raise BatchError("PREPARE_INPUT_STALE", "Pinned input hash no longer matches", path=artifact["path"])
    return path


def _target(task_id: str, method: str, stage: str, mode: str | None, run_id: str,
            base_sha: str, task_manifest: dict[str, str], policy: dict[str, str] | None) -> dict[str, Any]:
    identity = {"task_id": task_id, "method": method, "stage": stage, "mode": mode, "run_id": run_id}
    return {
        "target_id": "target-" + canonical_sha256(identity)[:24],
        **identity, "base_sha": base_sha, "task_manifest": task_manifest, "policy": policy,
    }


def compile_experiment(config_path: Path, *, repository_root: Path = ROOT) -> dict[str, Any]:
    """Validate every pinned input and return a deterministic v1 manifest."""
    root = repository_root.resolve()
    config_path = config_path.resolve()
    if not config_path.is_file() or not config_path.is_relative_to(root):
        raise BatchError("PREPARE_CONFIG_INVALID", "Config must be a repository file")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise BatchError("PREPARE_CONFIG_INVALID", "Config must be a JSON object")
    if isinstance(config.get("prs"), list) and len(config["prs"]) != len(set(map(str, config["prs"]))):
        raise BatchError("PREPARE_DUPLICATE_PR", "PR appears more than once")
    _validate(config, "experiment-config-v1.schema.json")
    source_path = _pinned(root, config["source_batch"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    _validate(source, "batch-run-v1.schema.json")
    approved = source["approved_plan"]
    plan = json.loads(_pinned(root, {"path": approved["path"], "sha256": approved["sha256"]}).read_text(encoding="utf-8"))
    report = json.loads(_pinned(root, {"path": approved["provision_report_path"], "sha256": approved["provision_report_sha256"]}).read_text(encoding="utf-8"))
    if plan.get("plan_id") != approved["plan_id"] or report.get("status") not in {"READY", "TOPOLOGY_WARNING"} or report.get("plan", {}).get("explicitly_approved_plan_id") != approved["plan_id"] or report.get("plan", {}).get("sha256") != approved["sha256"]:
        raise BatchError("PREPARE_PLAN_MISMATCH", "Source batch approval does not match pinned plan")
    planned = {item["task_id"]: item for item in plan["tasks"]}
    source_tasks = {entry["task_id"]: entry for entry in source["tasks"]}
    if len(source_tasks) != len(source["tasks"]):
        raise BatchError("PREPARE_SOURCE_DUPLICATE", "Source batch contains duplicate tasks")
    evaluation = config["evaluation"]
    if evaluation["kind"] == "host-plan":
        evaluation_plan = json.loads(_pinned(root, evaluation["plan"]).read_text(encoding="utf-8"))
        if evaluation_plan.get("batch_config") != config["source_batch"]:
            raise BatchError("PREPARE_EVALUATION_MISMATCH", "Evaluation plan does not bind to source batch")
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str | None, str]] = set()
    for pr in config["prs"]:
        task_id = f"scrapy__scrapy__pr{pr}"
        if task_id not in source_tasks or task_id not in planned:
            raise BatchError("PREPARE_PR_NOT_IN_SOURCE", "PR is absent from pinned source batch", pr=pr)
        task = source_tasks[task_id]
        task_path = _pinned(root, task["task_manifest"])
        task_data = json.loads(task_path.read_text(encoding="utf-8"))
        base_sha = task_data.get("baseline", {}).get("base_sha")
        if task_data.get("task_id") != task_id or base_sha != planned[task_id]["baseline"]["base_sha"]:
            raise BatchError("PREPARE_TASK_MISMATCH", "Task identity differs from approved plan", task_id=task_id)
        source_methods = {item["method"]: item for item in task["methods"]}
        if len(source_methods) != len(task["methods"]):
            raise BatchError("PREPARE_SOURCE_DUPLICATE", "Source batch contains duplicate methods", task_id=task_id)
        for method in config["methods"]:
            if method not in source_methods:
                raise BatchError("PREPARE_METHOD_NOT_IN_SOURCE", "Method is absent from pinned source batch", task_id=task_id, method=method)
            entry = source_methods[method]
            if "detect" in config["stages"]:
                targets.append(_target(task_id, method, "detect", None, entry["detect"]["run_id"], base_sha, task["task_manifest"], None))
            if "update" in config["stages"]:
                by_mode = {item["mode"]: item for item in entry["updates"]}
                if len(by_mode) != len(entry["updates"]):
                    raise BatchError("PREPARE_SOURCE_DUPLICATE", "Source batch contains duplicate update modes", task_id=task_id, method=method)
                for mode in config["update_modes"]:
                    if mode not in by_mode:
                        raise BatchError("PREPARE_MODE_NOT_IN_SOURCE", "Update mode is absent from pinned source batch", task_id=task_id, method=method, mode=mode)
                    update = by_mode[mode]
                    policy_path = _pinned(root, update["policy"])
                    policy = json.loads(policy_path.read_text(encoding="utf-8"))
                    if any(policy.get(field) != value for field, value in {
                        "task_id": task_id, "method": method, "stage": "update", "mode": mode,
                        "run_id": update["run_id"], "base_sha": base_sha,
                        "task_manifest_sha256": task["task_manifest"]["sha256"],
                    }.items()):
                        raise BatchError("PREPARE_POLICY_MISMATCH", "Pinned policy differs from target", task_id=task_id, method=method, mode=mode)
                    targets.append(_target(task_id, method, "update", mode, update["run_id"], base_sha, task["task_manifest"], update["policy"]))
    for target in targets:
        identity = (target["task_id"], target["method"], target["stage"], target["mode"], target["run_id"])
        if identity in seen:
            raise BatchError("PREPARE_TARGET_DUPLICATE", "Expanded target is duplicated", target=str(identity))
        seen.add(identity)
    manifest = {
        "schema_version": 1, "manifest_type": "PREPARED_EXPERIMENT", "experiment_id": config["experiment_id"],
        "inputs": {
            "user_config": {"path": config_path.relative_to(root).as_posix(), "sha256": sha256_file(config_path)},
            "source_batch": config["source_batch"], "batch_id": source["batch_id"],
            "approved_plan": approved, "evaluation": evaluation,
        },
        "target_count": len(targets), "targets": targets,
    }
    manifest["prepared_id"] = "prepared-" + canonical_sha256(manifest)[:24]
    _validate(manifest, "prepared-manifest-v1.schema.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a pinned SDD experiment without running it")
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        manifest = compile_experiment(args.config)
        if args.output:
            write_json(args.output, manifest, refuse_overwrite=True)
        else:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
    except (BatchError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
