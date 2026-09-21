"""Recoverable preparation over pinned, already approved batch inputs.

Each step is checked again on resume. The mutable state is only a progress hint;
the frozen manifest and its referenced files are the authority for P3.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from .core import BatchError, canonical_sha256, sha256_file, validate_plan_inputs, write_json
from .image_recipes import create as create_image_recipe, verify_directory
from .gold_audit import run_audit
from .compose_preflight import run_preflight
from .stages import validate_update_policy
from .provision import provision_plan
from .scaffold import scaffold_tasks
from .update_policy import select_update_policy
from .prepare import BENCH, ROOT, _pinned, _validate, compile_experiment

STEPS = ("inputs", "baseline", "images", "scaffold", "gold", "preflight", "update_policy")


def _document(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise BatchError("PREPARE_EVIDENCE_MISSING", "Required preparation evidence is absent", path=str(path))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BatchError("PREPARE_EVIDENCE_INVALID", "Evidence must be a JSON object", path=str(path))
    return value


def _artifact(root: Path, path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise BatchError("PREPARE_EVIDENCE_MISSING", "Required evidence file is absent or unsafe", path=str(path))
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def _require(condition: bool, code: str, message: str, **details: Any) -> None:
    if not condition:
        raise BatchError(code, message, **details)


def verify_step(step: str, manifest: dict[str, Any], root: Path = ROOT, *,
                generate_missing: bool = False) -> list[dict[str, str]]:
    """Verify existing evidence; never trust a prior progress marker alone."""
    root = root.resolve()
    bench = root / "sdd-bench/scrapy-sdd"
    inputs = manifest["inputs"]
    tasks = {target["task_id"]: target for target in manifest["targets"]}
    evidence: list[dict[str, str]] = []
    if step == "inputs":
        for item in (inputs["user_config"], inputs["source_batch"]):
            _pinned(root, item)
            evidence.append(item)
        for path, digest in ((inputs["approved_plan"]["path"], inputs["approved_plan"]["sha256"]),
                             (inputs["approved_plan"]["provision_report_path"], inputs["approved_plan"]["provision_report_sha256"])):
            item = {"path": path, "sha256": digest}
            _pinned(root, item)
            evidence.append(item)
        if inputs["evaluation"]["kind"] == "host-plan":
            _pinned(root, inputs["evaluation"]["plan"])
            evidence.append(inputs["evaluation"]["plan"])
        plan = _document(root / inputs["approved_plan"]["path"])
        _require(validate_plan_inputs(plan, root)["valid"], "PREPARE_INPUT_STALE", "Approved plan inputs are stale")
    elif step == "baseline":
        for image in manifest["images"]:
            _pinned(root, image["baseline_lock"])
            lock = _document(root / image["baseline_lock"]["path"])
            _require(lock.get("base_sha") == image["base_sha"], "PREPARE_BASELINE_CONFLICT", "Baseline lock base differs", base_sha=image["base_sha"])
            evidence.append(image["baseline_lock"])
    elif step == "images":
        for image in manifest["images"]:
            _pinned(root, image["deployment_lock"])
            lock = _document(root / image["deployment_lock"]["path"])
            _require(lock.get("status") == "READY" and lock.get("base_sha") == image["base_sha"]
                     and lock.get("baseline_lock_sha256") == image["baseline_lock"]["sha256"]
                     and all(all(lock.get("images", {}).get(role, {}).get(field) == image[role][field]
                                 for field in ("tag", "image_id")) for role in ("agent", "baseline")),
                     "PREPARE_IMAGE_CONFLICT", "Deployment lock differs from prepared image identity", base_sha=image["base_sha"])
            _require(verify_directory(bench, image["base_sha"], root)["status"] == "PASS", "PREPARE_IMAGE_CONFLICT", "Image recipe failed verification", base_sha=image["base_sha"])
            audit_path = bench / "batch/audits/images" / f'{image["base_sha"]}-image-audit.json'
            audit = _document(audit_path)
            _require(audit.get("status") == "PASS" and audit.get("deployment_lock", {}).get("sha256") == image["deployment_lock"]["sha256"],
                     "PREPARE_IMAGE_AUDIT_INVALID", "Image audit does not match deployment", base_sha=image["base_sha"])
            evidence.extend((image["deployment_lock"], _artifact(root, audit_path)))
    elif step == "scaffold":
        for task_id, target in tasks.items():
            _pinned(root, target["task_manifest"])
            task = root / target["task_manifest"]["path"]
            data = _document(task)
            _require(data.get("task_id") == task_id and data.get("baseline", {}).get("base_sha") == target["base_sha"],
                     "PREPARE_TASK_CONFLICT", "Task identity differs from manifest", task_id=task_id)
            _artifact(root, task.parent / "compose.yaml")
            _artifact(root, task.parent / "experiment-inputs/task.md")
            evidence.extend((target["task_manifest"], _artifact(root, task.parent / "experiment-inputs/task.md")))
    elif step == "gold":
        for task_id in tasks:
            task = bench / "tasks" / task_id
            audit_path = task / "isolation-audit.json"
            if generate_missing and not audit_path.exists():
                run_audit(task=task, plan_path=root / inputs["approved_plan"]["path"], bench=bench, repository_root=root)
            audit = _document(audit_path)
            _require(audit.get("status") == "PASS" and audit.get("task_id") == task_id and audit.get("gold_values_recorded") is False,
                     "PREPARE_GOLD_AUDIT_INVALID", "Gold isolation audit is invalid", task_id=task_id)
            evidence.append(_artifact(root, audit_path))
            for method in {t["method"] for t in manifest["targets"] if t["task_id"] == task_id}:
                for stage in ("detect", "update"):
                    directory = task / "runs" / method / stage / "audit"
                    report = _document(directory / "gold-check-report.json")
                    provenance = _document(directory / "prompt-provenance.json")
                    visible = directory / "visible-files.sha256"
                    _require(report.get("status") == "PASS" and provenance.get("gold_used") is False
                             and provenance.get("patch_used") is False and visible.is_file()
                             and not any("gold" in line.lower() for line in visible.read_text(encoding="utf-8").splitlines()),
                             "PREPARE_GOLD_VISIBLE", "Agent-visible input or audit contains gold", task_id=task_id, method=method, stage=stage)
                    evidence.extend((_artifact(root, directory / "gold-check-report.json"), _artifact(root, visible)))
    elif step == "preflight":
        for task_id in tasks:
            task = bench / "tasks" / task_id
            summary_path = task / "preflight-summary.json"
            if generate_missing and not summary_path.exists():
                run_preflight(task=task, bench=bench, repository_root=root, run_id="preflight-" + manifest["prepared_id"][9:])
            summary = _document(summary_path)
            _require(summary.get("task_id") == task_id and summary.get("runtime_preflight_status") == "READY"
                     and summary.get("model_request_sent") is False,
                     "PREPARE_PREFLIGHT_INVALID", "Runtime preflight is not ready", task_id=task_id)
            lock_path = task / "compose-deployment-lock.json"
            _require(sha256_file(lock_path) == summary.get("compose_deployment_lock_sha256"),
                     "PREPARE_PREFLIGHT_CONFLICT", "Compose deployment lock differs", task_id=task_id)
            evidence.extend((_artifact(root, summary_path), _artifact(root, lock_path)))
            reports = {(r["method"], r["stage"]): r for r in summary.get("reports", [])}
            for target in (t for t in manifest["targets"] if t["task_id"] == task_id):
                record = reports.get((target["method"], target["stage"]))
                _require(record is not None and record.get("runtime_boundary_pass") is True,
                         "PREPARE_PREFLIGHT_INVALID", "Target runtime boundary is not ready", target_id=target["target_id"])
                _pinned(root, {"path": record["report"], "sha256": record["report_sha256"]})
    elif step == "update_policy":
        for target in manifest["targets"]:
            if target["stage"] != "update":
                continue
            policy_path = _pinned(root, target["policy"])
            policy = _document(policy_path)
            validate_update_policy(task_manifest=root / target["task_manifest"]["path"], policy_path=policy_path,
                                   bench=bench, method=target["method"], run_id=target["run_id"],
                                   expected_file_sha256=target["policy"]["sha256"])
            _require(all(policy.get(field) == target[field] for field in ("task_id", "method", "stage", "mode", "run_id", "base_sha"))
                     and policy.get("gold_blind") is True and policy.get("detect_must_complete_first") is True,
                     "PREPARE_POLICY_CONFLICT", "Update policy does not match target", target_id=target["target_id"])
            evidence.append(target["policy"])
    else:
        raise ValueError(f"Unknown prepare step: {step}")
    return evidence


def load_prepared(path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    """P3 entrypoint: validate frozen manifest, all source hashes, and evidence."""
    manifest = _document(path)
    _validate(manifest, "prepared-manifest-v1.schema.json")
    payload = dict(manifest)
    supplied = payload.pop("prepared_id")
    _require(supplied == "prepared-" + canonical_sha256(payload)[:24], "PREPARE_MANIFEST_CONFLICT", "Prepared ID differs from contents")
    _require(manifest["target_count"] == len(manifest["targets"]), "PREPARE_MANIFEST_CONFLICT", "Target count differs")
    _require({i["base_sha"] for i in manifest["images"]} == {t["base_sha"] for t in manifest["targets"]},
             "PREPARE_MANIFEST_CONFLICT", "Image bases differ from targets")
    for step in STEPS:
        verify_step(step, manifest, root)
    return manifest


def _ensure_legacy_inputs(config_path: Path, root: Path) -> None:
    """Use existing generators only for absent artifacts, then enforce pinned hashes.

    Existing files are never overwritten. A generator that cannot reproduce a
    pinned identity is a conflict, not an invitation to change the source batch.
    """
    bench = root / "sdd-bench/scrapy-sdd"
    config = _document(config_path)
    _validate(config, "experiment-config-v1.schema.json")
    source = _document(_pinned(root, config["source_batch"]))
    _validate(source, "batch-run-v1.schema.json")
    approved = source["approved_plan"]
    plan_path = _pinned(root, {"path": approved["path"], "sha256": approved["sha256"]})
    plan = _document(plan_path)
    report_path = root / approved["provision_report_path"]
    if not report_path.exists():
        source_repository = bench / "batch/sources/scrapy"
        result = provision_plan(plan=plan, plan_path=plan_path, approved_plan_id=approved["plan_id"],
                                bench_root=bench, repository_root=root, source_repository=source_repository)
        # Check the bytes before publishing the report named by source_batch.
        encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        import hashlib
        _require(hashlib.sha256(encoded).hexdigest() == approved["provision_report_sha256"],
                 "PREPARE_INPUT_STALE", "Generated provision report differs from pinned identity")
        write_json(report_path, result, refuse_overwrite=True)
    _pinned(root, {"path": approved["provision_report_path"], "sha256": approved["provision_report_sha256"]})
    by_task = {entry["task_id"]: entry for entry in source["tasks"]}
    selected = [f"scrapy__scrapy__pr{pr}" for pr in config["prs"]]
    for task_id in selected:
        _require(task_id in by_task, "PREPARE_PR_NOT_IN_SOURCE", "PR absent from source batch", task_id=task_id)
    bases = {next(item for item in plan["tasks"] if item["task_id"] == task_id)["baseline"]["base_sha"] for task_id in selected}
    for base_sha in sorted(bases):
        baseline = bench / "batch/baselines" / base_sha / "baseline-lock.json"
        _require(baseline.is_file(), "PREPARE_BASELINE_MISSING", "Pinned baseline is missing", base_sha=base_sha)
        image_dir = bench / "batch/images" / base_sha
        if not image_dir.exists():
            create_image_recipe(bench, root, base_sha)
        deployment = image_dir / "deployment-lock.json"
        if not deployment.exists():
            script = image_dir / "build-images.sh"
            _require(script.is_file(), "PREPARE_IMAGE_SCRIPT_MISSING", "Image build recipe is incomplete", base_sha=base_sha)
            result = subprocess.run(["bash", str(script.resolve())], cwd=image_dir, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, check=False)
            _require(result.returncode == 0, "PREPARE_IMAGE_BUILD_FAILED", "Image build failed", base_sha=base_sha, exit_code=result.returncode)
    if any(not (root / by_task[task_id]["task_manifest"]["path"]).exists() for task_id in selected):
        scaffold_tasks(plan_path=plan_path, provision_report_path=report_path,
                       approved_plan_id=approved["plan_id"], bench_root=bench, repository_root=root)
    for task_id in selected:
        task = by_task[task_id]
        _pinned(root, task["task_manifest"])
        task_dir = bench / "tasks" / task_id
        for method in task["methods"]:
            for update in method["updates"]:
                artifact = update["policy"]
                if not (root / artifact["path"]).exists():
                    select_update_policy(task=task_dir, bench=bench, repository_root=root,
                                         method=method["method"], mode=update["mode"], run_id=update["run_id"])
                _pinned(root, artifact)


def prepare(config_path: Path, output_dir: Path, *, root: Path = ROOT,
            after_step: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Verify or resume each step, then freeze a manifest without overwriting it."""
    root = root.resolve()
    output_dir = output_dir.resolve()
    _require(output_dir.is_relative_to(root), "PREPARE_PATH_INVALID", "Output must be inside repository")
    _ensure_legacy_inputs(config_path.resolve(), root)
    manifest = compile_experiment(config_path, repository_root=root)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "state.json"
    frozen_path = output_dir / "prepared-manifest.json"
    if frozen_path.exists():
        existing = load_prepared(frozen_path, root=root)
        _require(existing == manifest, "PREPARE_MANIFEST_CONFLICT", "Frozen manifest differs from current inputs")
        return existing
    state = _document(state_path) if state_path.exists() else {"schema_version": 1, "prepared_id": manifest["prepared_id"], "status": "IN_PROGRESS", "steps": {}}
    _require(state.get("prepared_id") == manifest["prepared_id"], "PREPARE_STATE_CONFLICT", "Progress state belongs to different inputs")
    for step in STEPS:
        evidence = verify_step(step, manifest, root, generate_missing=True)
        digest = canonical_sha256(evidence)
        previous = state["steps"].get(step)
        if previous is not None:
            _require(previous["evidence_sha256"] == digest, "PREPARE_EVIDENCE_CONFLICT", "Completed step evidence changed", step=step)
        state["steps"][step] = {"status": "VERIFIED", "evidence_sha256": digest, "file_count": len(evidence)}
        write_json(state_path, state)
        if after_step:
            after_step(step)
    write_json(frozen_path, manifest, refuse_overwrite=True)
    state["status"] = "FROZEN"
    write_json(state_path, state)
    load_prepared(frozen_path, root=root)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and freeze a resumable SDD prepared manifest")
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.config, args.output_dir)
        print(json.dumps({"status": "FROZEN", "prepared_id": result["prepared_id"], "target_count": result["target_count"]}))
    except (BatchError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
