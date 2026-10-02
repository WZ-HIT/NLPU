"""Create gold-blind two-stage task scaffolds from approved provision results."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .core import BatchError, canonical_sha256, display_path, sha256_file, validate_plan_inputs, write_json

METHODS: dict[str, dict[str, Any]] = {
    "openspec": {
        "version": "1.12.0",
        "command": ["openspec", "init", "--tools", "codex"],
        "generated_roots": [".agents/skills/", "openspec/"],
        "detect_phases": ["propose", "detect"],
        "update_phases": ["apply"],
        "planning_workspace_path": "openspec/changes/",
        "planning_mount_path": "/workspace/openspec/changes",
        "reference_manifest_sha256": "70168a45d79ce6cd6d686c280476e3fbaf57179cc239cda700b49cac298c7141",
        "manifest_kind": "sha256",
        "evidence": "openspec-init-formal-12/step12-formal-hashes.txt",
    },
    "speckit": {
        "version": "1.0.4",
        "command": ["specify", "init", "--here", "--force", "--non-interactive", "--script", "sh", "--integration", "codex", "--integration-options=--skills"],
        "generated_roots": [".agents/skills/", ".specify/"],
        "detect_phases": ["specify", "plan", "tasks", "detect"],
        "update_phases": ["implement"],
        "planning_workspace_path": "specs/",
        "planning_mount_path": "/workspace/specs",
        "reference_manifest_sha256": "404c4d70c695f254aa9bd372bf0f0b508ce53c6f3ab4f8f8446931eda6c0ce34",
        "manifest_kind": "sha256",
        "evidence": "speckit-init-formal-16/generated-files.sha256",
    },
    "cc-sdd": {
        "version": "3.0.2",
        "command": ["cc-sdd", "--agent", "codex-skills", "--lang", "en", "--os", "linux", "--overwrite", "force", "--profile", "full"],
        "generated_roots": [".agents/", ".codex/", ".kiro/", "AGENTS.md"],
        "detect_phases": ["spec", "detect"],
        "update_phases": ["implement"],
        "planning_workspace_path": ".kiro/specs/",
        "planning_mount_path": "/workspace/.kiro/specs",
        "reference_manifest_sha256": "3be430c9092a6396aa0d9f5ae4be85f9d66ac33ee3cb986c175334503abf4cca",
        "manifest_kind": "sha256",
        "evidence": "cc-sdd-init-formal-20/generated-files.sha256",
    },
}

REFERENCE_TASK = "tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba"
REFERENCE_EVIDENCE = "Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_path(value: str) -> Path:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or "//" in value:
        raise BatchError("UNSAFE_PATH", "Path is not safe", path=value)
    return Path(*path.parts)


def _make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        try:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        except FileNotFoundError:
            pass


def _make_read_only(root: Path) -> None:
    for path in [*root.rglob("*"), root]:
        if path.is_symlink():
            continue
        try:
            path.chmod(path.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        except FileNotFoundError:
            pass


def prepare_codex_mountpoint(workspace: Path) -> None:
    """Create the target required for the isolated Codex tmpfs mount.

    Both stages' Compose files bind ``/workspace`` read-only and mount a tmpfs
    over ``/workspace/.codex``. runc resolves that mountpoint through the bind,
    so the directory has to be present in the workspace itself -- a read-only
    bind cannot have one created inside it. cc-sdd's frozen initialization
    happens to ship ``.codex/``, which is why openspec and speckit failed to
    start until this was made unconditional.

    Creating it is invisible to every digest that covers the Detect workspace:
    ``_content_manifest`` here and ``_workspace_content_sha256`` in ``stages``
    both hash files and never directories. So the frozen
    ``initial_workspace_sha256`` is the same either way, and the seal's
    "Detect did not touch the workspace" check is unaffected.
    """
    mountpoint = workspace / ".codex"
    if mountpoint.is_symlink() or (mountpoint.exists() and not mountpoint.is_dir()):
        raise BatchError(
            "INVALID_CODEX_MOUNTPOINT",
            "Update workspace .codex mountpoint must be a real directory",
        )
    mountpoint.mkdir(exist_ok=True)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise BatchError("GIT_VALIDATION_FAILED", "Git validation failed", repository=str(repo), argv=list(args), stderr=result.stderr[-1000:])
    return result.stdout.strip()


def _raw_record(raw_path: Path, repository: str, pr_id: int) -> dict[str, Any]:
    matches = []
    with raw_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("repo") == repository and item.get("pr_id") == pr_id:
                matches.append(item)
    if len(matches) != 1:
        raise BatchError("RAW_RECORD_NOT_UNIQUE", "Expected exactly one raw PR record", repository=repository, pr_id=pr_id, count=len(matches))
    return matches[0]


def _load_entries(bench_root: Path, method: str) -> list[dict[str, Any]]:
    config = METHODS[method]
    evidence = bench_root / REFERENCE_EVIDENCE / config["evidence"]
    if sha256_file(evidence) != config["reference_manifest_sha256"]:
        raise BatchError("INITIALIZATION_REFERENCE_CHANGED", "Frozen initialization manifest hash changed", method=method)
    source = bench_root / REFERENCE_TASK / "runs" / method / "scrapy"
    if config["manifest_kind"] == "json":
        entries = json.loads(evidence.read_text(encoding="utf-8"))
    else:
        entries = []
        for line in evidence.read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ", 1)
            src = source / _safe_path(relative)
            entries.append({"path": relative, "sha256": digest, "size_bytes": src.stat().st_size, "mode": oct(stat.S_IMODE(src.stat().st_mode))})
    entries = sorted(entries, key=lambda item: item["path"])
    for item in entries:
        relative = _safe_path(item["path"])
        src = source / relative
        if not src.is_file() or src.is_symlink() or sha256_file(src) != item["sha256"]:
            raise BatchError("INITIALIZATION_FILE_MISMATCH", "Frozen initialization file is missing or changed", method=method, path=item["path"])
    return entries


def _copy_entry(source_root: Path, destination_root: Path, entry: dict[str, Any]) -> None:
    relative = _safe_path(entry["path"])
    destination = destination_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_root / relative, destination)
    destination.chmod(int(entry["mode"], 8))


def _content_manifest(root: Path) -> tuple[list[dict[str, Any]], str]:
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts or not (path.is_file() or path.is_symlink()):
            continue
        data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        entries.append({"path": relative.as_posix(), "size_bytes": len(data), "sha256": __import__("hashlib").sha256(data).hexdigest()})
    return entries, canonical_sha256(entries)


def _validate_task_schema(task: dict[str, Any], schema_path: Path) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise BatchError("SCHEMA_VALIDATOR_UNAVAILABLE", "jsonschema is required for task validation") from exc
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(task), key=lambda error: list(error.path))
    if errors:
        raise BatchError("TASK_SCHEMA_INVALID", "Public task manifest failed schema validation", errors=[error.message for error in errors])


def _validate_approval(plan: dict[str, Any], plan_path: Path, report: dict[str, Any], report_path: Path, approved_plan_id: str, repository_root: Path) -> None:
    if plan.get("plan_id") != approved_plan_id:
        raise BatchError("PLAN_APPROVAL_MISMATCH", "Explicit plan approval does not match", expected=plan.get("plan_id"), supplied=approved_plan_id)
    if not validate_plan_inputs(plan, repository_root)["valid"]:
        raise BatchError("PLAN_INVALID", "Plan inputs are stale")
    report_plan = report.get("plan", {})
    if report.get("status") not in {"READY", "TOPOLOGY_WARNING"} or report_plan.get("explicitly_approved_plan_id") != approved_plan_id:
        raise BatchError("PROVISION_NOT_APPROVED", "Provision report does not prove explicit approval", report=str(report_path))
    if report_plan.get("sha256") != sha256_file(plan_path):
        raise BatchError("PROVISION_PLAN_HASH_MISMATCH", "Provision report references a different plan")


def scaffold_tasks(*, plan_path: Path, provision_report_path: Path, approved_plan_id: str, bench_root: Path, repository_root: Path, tasks_root: Path | None = None, task_ids: set[str] | None = None) -> list[dict[str, Any]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    provision = json.loads(provision_report_path.read_text(encoding="utf-8"))
    _validate_approval(plan, plan_path, provision, provision_report_path, approved_plan_id, repository_root)
    report_by_task = {item["task_id"]: item for item in provision["tasks"]}
    adapter_path = bench_root / "adapters/scrapy.json"
    adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    raw_path = repository_root / plan["inputs"]["raw"]["path"]
    results = []

    frozen_entries = {method: _load_entries(bench_root, method) for method in METHODS}
    tasks_root = tasks_root or bench_root / "tasks"
    for planned in plan["tasks"]:
        task_id = planned["task_id"]
        if task_ids is not None and task_id not in task_ids:
            continue
        provisioned = report_by_task.get(task_id)
        if not provisioned or provisioned["status"] == "BLOCKED":
            raise BatchError("TASK_NOT_PROVISIONED", "Task has no usable provision result", task_id=task_id)
        base_sha = planned["baseline"]["base_sha"]
        raw = _raw_record(raw_path, planned["repository"], planned["pr_id"])
        if raw.get("base_sha") != base_sha:
            raise BatchError("BASE_SHA_MISMATCH", "Raw base SHA differs from plan", task_id=task_id)
        title = raw.get("title")
        body = raw.get("body")
        if not isinstance(title, str) or not title.strip() or not isinstance(body, str):
            raise BatchError("INVALID_PUBLIC_DESCRIPTION", "Raw title/body are required", task_id=task_id)

        task_root = tasks_root / task_id
        if task_root.exists():
            existing_manifest = task_root / "task.json"
            if not existing_manifest.is_file():
                raise BatchError("TASK_ALREADY_EXISTS", "Existing task has no manifest", path=str(task_root))
            existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
            expected_public = {
                "task_id": task_id,
                "pr_id": planned["pr_id"],
                "base_sha": base_sha,
                "title": title,
                "body": body,
                "adapter_sha256": sha256_file(adapter_path),
            }
            actual_public = {
                "task_id": existing.get("task_id"),
                "pr_id": existing.get("pr_id"),
                "base_sha": existing.get("baseline", {}).get("base_sha"),
                "title": existing.get("title"),
                "body": existing.get("body"),
                "adapter_sha256": existing.get("adapter", {}).get("sha256"),
            }
            _validate_task_schema(existing, bench_root / "schemas/task-v1.schema.json")
            if actual_public != expected_public:
                raise BatchError(
                    "TASK_REUSE_MISMATCH", "Existing task does not match this approved PR/base/input",
                    task_id=task_id,
                )
            for method in METHODS:
                workspace = task_root / "runs" / method / "detect" / "workspace"
                if (
                    not (task_root / "initialization" / method / "manifest.json").is_file()
                    or not workspace.is_dir()
                    or _git(workspace, "rev-parse", "HEAD") != base_sha
                    or (task_root / "runs" / method / "update" / "workspace").exists()
                ):
                    raise BatchError(
                        "TASK_REUSE_INCOMPLETE", "Existing task cannot be safely reused",
                        task_id=task_id, method=method,
                    )
            if task_root.parent != bench_root / "tasks":
                lock_path = task_root / "initial-workspaces.json"
                if not lock_path.is_file():
                    raise BatchError("TASK_REUSE_INCOMPLETE", "Round workspace lock is missing", task_id=task_id)
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                by_method = {item["method"]: item for item in lock.get("workspaces", [])}
                for method in METHODS:
                    expected = by_method.get(method, {}).get("initial_workspace_sha256")
                    actual = _content_manifest(task_root / "runs" / method / "detect" / "workspace")[1]
                    if actual != expected:
                        raise BatchError("TASK_REUSE_CONFLICT", "Round workspace changed since scaffolding", task_id=task_id, method=method)
            results.append({
                "task_id": task_id, "status": "REUSED_VERIFIED",
                "path": display_path(task_root, repository_root),
                "initializations": {
                    method: {
                        "path": f"initialization/{method}/manifest.json",
                        "sha256": sha256_file(task_root / "initialization" / method / "manifest.json"),
                    }
                    for method in METHODS
                },
                "update_workspaces_created": False,
            })
            continue
        task_root.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{task_id}.", dir=task_root.parent))
        try:
            owner, name = planned["repository"].split("/", 1)
            public_task = {
                "schema_version": 1,
                "task_id": task_id,
                "repository": {"owner": owner, "name": name},
                "pr_id": planned["pr_id"],
                "baseline": {"base_sha": base_sha},
                "title": title,
                "body": body,
                "adapter": {"id": adapter["adapter_id"], "version": adapter["schema_version"], "path": display_path(adapter_path, repository_root), "sha256": sha256_file(adapter_path)},
            }
            _validate_task_schema(public_task, bench_root / "schemas/task-v1.schema.json")
            write_json(temporary / "task.json", public_task)
            task_md = f"# Pull request task\n\nRepository: `{planned['repository']}`\n\nPull request: `{planned['pr_id']}`\n\nBase commit: `{base_sha}`\n\n## Title\n\n{title}\n\n## Body\n\n{body}\n"
            (temporary / "experiment-inputs").mkdir()
            (temporary / "experiment-inputs/task.md").write_text(task_md, encoding="utf-8")

            baseline_dir = bench_root / "batch/baselines" / base_sha
            baseline_repo = baseline_dir / "repository"
            baseline_lock_path = baseline_dir / "baseline-lock.json"
            baseline_lock = json.loads(baseline_lock_path.read_text(encoding="utf-8"))
            deployment_path = bench_root / "batch/images" / base_sha / "deployment-lock.json"
            deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
            if baseline_lock.get("base_sha") != base_sha or deployment.get("base_sha") != base_sha or deployment.get("status") != "READY":
                raise BatchError("LOCK_MISMATCH", "Baseline or deployment lock does not match task", task_id=task_id)

            workspace_records = []
            initialization_records = {}
            for method, config in METHODS.items():
                source_root = bench_root / REFERENCE_TASK / "runs" / method / "scrapy"
                init_root = temporary / "initialization" / method
                init_files = init_root / "files"
                detect_root = temporary / "runs" / method / "detect"
                update_root = temporary / "runs" / method / "update"
                workspace = detect_root / "workspace"
                planning = detect_root / "planning-artifacts"
                output = detect_root / "output"
                update_output = update_root / "output"
                shutil.copytree(baseline_repo, workspace, symlinks=True)
                _make_writable(workspace)
                for entry in frozen_entries[method]:
                    _copy_entry(source_root, init_files, entry)
                    _copy_entry(source_root, workspace, entry)
                (workspace / _safe_path(config["planning_workspace_path"])).mkdir(parents=True, exist_ok=True)
                # Before the freeze below, which strips the write bits that
                # mkdir needs. Both stages mount a tmpfs over this path.
                prepare_codex_mountpoint(workspace)
                planning.mkdir(parents=True)
                output.mkdir()
                update_output.mkdir(parents=True)
                (output / ".gitkeep").write_bytes(b"")
                (update_output / ".gitkeep").write_bytes(b"")
                if method == "openspec":
                    (planning / "archive").mkdir()
                    (planning / "archive/.gitkeep").write_bytes(b"")
                head = _git(workspace, "rev-parse", "HEAD")
                tree = _git(workspace, "rev-parse", "HEAD^{tree}")
                tracked_diff = _git(workspace, "diff", "--name-only")
                if head != base_sha or tree != baseline_lock["tree_sha"] or tracked_diff:
                    raise BatchError("WORKSPACE_BASE_MISMATCH", "Detect workspace does not preserve the pure baseline", method=method)
                init_manifest = {
                    "schema_version": 1,
                    "manifest_type": "FROZEN_SDD_INITIALIZATION",
                    "method": method,
                    "version": config["version"],
                    "initialization_command": {"argv": config["command"], "network": "none", "model_request": False},
                    "generated_roots": config["generated_roots"],
                    "files": frozen_entries[method],
                    "file_count": len(frozen_entries[method]),
                    "files_manifest_sha256": canonical_sha256(frozen_entries[method]),
                    "reference_manifest_sha256": config["reference_manifest_sha256"],
                    "planning_artifacts": {"workspace_path": config["planning_workspace_path"], "writable_mount_path": config["planning_mount_path"], "sealed_at_freeze": True},
                    "workflow": {"detect_phases": config["detect_phases"], "freeze": "seal_detection_manifest_and_planning_artifacts", "update_phases": config["update_phases"]},
                }
                write_json(init_root / "manifest.json", init_manifest)
                files, workspace_sha = _content_manifest(workspace)
                _make_read_only(workspace)
                write_json(detect_root / "stage.json", {
                    "schema_version": 1, "stage": "detect", "method": method, "status": "READY",
                    "phases": config["detect_phases"], "workspace": "workspace/", "planning_artifacts": "planning-artifacts/", "output": "output/",
                    "repository_mount": "read-only", "planning_mount": {"host": "planning-artifacts/", "container": config["planning_mount_path"], "mode": "read-write"},
                    "forbidden": ["run_tests", "modify_scrapy", "modify_tests", "modify_project_configuration"],
                })
                write_json(update_root / "stage.json", {
                    "schema_version": 1, "stage": "update", "method": method, "status": "AWAITING_DETECT_SEAL",
                    "phases": config["update_phases"], "workspace": None, "workspace_created": False, "output": "output/",
                    "reconstruct_from": ["pure_baseline", "frozen_initialization", "sealed_detection_artifacts"],
                    "repository_mount": "read-only", "writable_paths": ["/workspace/tests"],
                    "forbidden": ["run_tests", "modify_scrapy", "modify_project_configuration"],
                })
                workspace_records.append({
                    "method": method, "base_sha": head, "tree_sha": tree,
                    "baseline_checkout_manifest_sha256": baseline_lock["checkout_manifest_sha256"],
                    "initialization_manifest_sha256": sha256_file(init_root / "manifest.json"),
                    "workspace_file_count": len(files), "initial_workspace_sha256": workspace_sha,
                    "detect_workspace": f"runs/{method}/detect/workspace/", "update_workspace_created": False,
                })
                initialization_records[method] = {"path": f"initialization/{method}/manifest.json", "sha256": sha256_file(init_root / "manifest.json")}

            stage_policy = {
                "schema_version": 1, "policy_type": "DETECT_UPDATE_STAGE_POLICY", "task_id": task_id,
                "fresh_container_per_stage": True,
                "shared_state": {"container": False, "workspace": False, "home": False, "cache": False, "model_session": False},
                "global_forbidden_actions": ["run_tests", "modify_production_code", "install_dependencies", "access_network"],
                "methods": {
                    method: {
                        "detect": {"status": "READY", "workspace_created": True, "workspace": f"runs/{method}/detect/workspace/", "repository_mount": "read-only", "writable_paths": [METHODS[method]["planning_mount_path"], "/output"], "phases": METHODS[method]["detect_phases"]},
                        "freeze": {"required": True, "outputs": ["detection-manifest.json", "planning-artifacts/"], "immutable_after_seal": True},
                        "update": {"status": "AWAITING_DETECT_SEAL", "workspace_created": False, "workspace": None, "repository_mount": "read-only", "writable_paths": ["/workspace/tests", "/output"], "phases": METHODS[method]["update_phases"]},
                    } for method in METHODS
                },
            }
            write_json(temporary / "stage-policy.json", stage_policy)
            workspace_lock = {
                "schema_version": 1, "lock_type": "INITIAL_DETECT_WORKSPACES", "task_id": task_id,
                "base_sha": base_sha, "tree_sha": baseline_lock["tree_sha"],
                "baseline_lock": {"path": display_path(baseline_lock_path, repository_root), "sha256": sha256_file(baseline_lock_path)},
                "deployment_lock": {"path": display_path(deployment_path, repository_root), "sha256": sha256_file(deployment_path), "agent_image_id": deployment["images"]["agent"]["image_id"]},
                "business_source_manifest_sha256": baseline_lock["checkout_manifest_sha256"],
                "all_methods_share_base_and_business_source": len({(r["base_sha"], r["tree_sha"], r["baseline_checkout_manifest_sha256"]) for r in workspace_records}) == 1,
                "workspaces": workspace_records,
            }
            write_json(temporary / "initial-workspaces.json", workspace_lock)
            task_report = {
                "schema_version": 1, "report_type": "PROVISION_REPORT", "generated_at_utc": _utc_now(),
                "plan": {"plan_id": plan["plan_id"], "path": display_path(plan_path, repository_root), "sha256": sha256_file(plan_path), "explicitly_approved_plan_id": approved_plan_id},
                "status": "READY", "task_count": 1,
                "tasks": [{
                    "task_id": task_id, "repository": planned["repository"], "pr_id": planned["pr_id"], "status": "READY",
                    "base_sha": base_sha, "tree_sha": baseline_lock["tree_sha"], "baseline_cache_reused": True,
                    "baseline_lock": {"path": display_path(baseline_lock_path, repository_root), "sha256": sha256_file(baseline_lock_path)},
                    "topology_audit": provisioned["topology_audit"],
                    "variant_workspaces": {m: display_path(task_root / "runs" / m / "detect" / "workspace", repository_root) for m in METHODS},
                    "blocking_errors": [], "warnings": [],
                }],
                "operations": {"baseline_cache_created_or_verified": True, "independent_variant_workspaces_created": True, "docker_images_created": False, "containers_created": False, "volumes_created": False, "networks_created": False, "agents_started": False, "tests_run": False},
            }
            write_json(temporary / "provision-report.json", task_report)

            metadata_paths = [temporary / "task.json", temporary / "experiment-inputs/task.md", temporary / "stage-policy.json", temporary / "initial-workspaces.json", temporary / "provision-report.json"]
            metadata_paths += [temporary / value["path"] for value in initialization_records.values()]
            text = b"\n".join(path.read_bytes() for path in metadata_paths)
            forbidden = [b"TEST_ONLY_PR", b"MIXED_CODE_AND_TEST_PR", b'"changed_files"', b'"gold_test"', b'"head_sha"', b'"merge_commit_sha"']
            for key in ("head_sha", "merge_commit_sha"):
                value = raw.get(key)
                if isinstance(value, str) and value:
                    forbidden.append(value.encode())
            public_nl = (title + "\n" + body).encode()
            target_paths = {change.get("file") for change in raw.get("test_changes", []) if isinstance(change, dict)}
            target_paths.update(change.get("filename") for change in raw.get("changed_files", []) if isinstance(change, dict))
            forbidden.extend(path.encode() for path in target_paths if isinstance(path, str) and path and path.encode() not in public_nl)
            hits = [value.decode(errors="replace") for value in forbidden if value and value in text]
            if hits:
                raise BatchError("AGENT_VISIBLE_LEAK", "Generated agent-visible metadata contains host-only information", hit_count=len(hits))
            if not workspace_lock["all_methods_share_base_and_business_source"]:
                raise BatchError("WORKSPACE_DIVERGENCE", "Method workspaces do not share the same baseline")
            for method in METHODS:
                workspace = temporary / "runs" / method / "detect" / "workspace"
                if any(path.stat().st_mode & 0o222 for path in [workspace, workspace / "scrapy", workspace / "tests"]):
                    raise BatchError("DETECT_PERMISSION_INVALID", "Detect workspace must be read-only", method=method)
                if (temporary / "runs" / method / "update" / "workspace").exists():
                    raise BatchError("UPDATE_WORKSPACE_CREATED_EARLY", "Update workspace must not exist before freeze", method=method)
            os.replace(temporary, task_root)
            results.append({"task_id": task_id, "status": "READY", "path": display_path(task_root, repository_root), "initializations": initialization_records, "update_workspaces_created": False})
        except Exception:
            _make_writable(temporary)
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    return results
