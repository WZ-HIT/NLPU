"""Host-only pure-baseline provisioning and Git topology auditing."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import (
    BatchError,
    ID_RE,
    canonical_sha256,
    display_path,
    sha256_bytes,
    sha256_file,
    validate_plan_inputs,
    write_json,
)

GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VARIANTS = ("openspec", "speckit", "cc-sdd")
PLAN_FIELDS = {
    "schema_version", "plan_id", "plan_type", "created_at_utc", "status",
    "executable", "repository_scope", "inputs", "input_set_sha256",
    "inventory", "selection", "task_scope", "tasks", "approval",
}
TASK_FIELDS = {
    "task_id", "repository", "pr_id", "baseline", "classification",
    "member_sample_ids", "member_sample_count", "test_change_count",
    "changed_files", "nl_quality", "task_categories",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise BatchError(
            "GIT_COMMAND_FAILED",
            "Git command failed during host-only provisioning",
            repository=str(repo),
            argv=["git", "-C", str(repo), *args],
            exit_code=result.returncode,
            stderr=result.stderr.decode("utf-8", errors="replace")[-2000:],
        )
    return result


def _decode_lines(value: bytes) -> list[str]:
    return [
        line
        for line in value.decode("utf-8", errors="strict").splitlines()
        if line
    ]


def _object_exists(repo: Path, sha: str | None) -> bool:
    if not sha or not GIT_SHA_RE.fullmatch(sha):
        return False
    return _git(repo, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def _reflog_paths(repo: Path) -> list[str]:
    logs = repo / ".git/logs"
    if not logs.exists():
        return []
    return sorted(
        path.relative_to(repo / ".git").as_posix()
        for path in logs.rglob("*")
        if path.is_file()
    )


def git_topology(repo: Path, *, base_sha: str, head_sha: str | None, merge_sha: str | None) -> dict[str, Any]:
    is_repo = _git(repo, "rev-parse", "--is-inside-work-tree", check=False)
    if is_repo.returncode or is_repo.stdout.strip() != b"true":
        return {
            "repository": str(repo),
            "valid_git_repository": False,
            "status": "BLOCKED",
            "issues": ["not a Git working-tree repository"],
        }
    head = _git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").stdout.decode().strip()
    refs = _decode_lines(
        _git(repo, "for-each-ref", "--format=%(refname)").stdout
    )
    remotes = _decode_lines(_git(repo, "remote").stdout)
    branches = _decode_lines(
        _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/").stdout
    )
    tags = _decode_lines(
        _git(repo, "for-each-ref", "--format=%(refname)", "refs/tags/").stdout
    )
    reachable = _decode_lines(_git(repo, "rev-list", "HEAD").stdout)
    shallow = (repo / ".git/shallow").is_file()
    worktree_status = _decode_lines(
        _git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
    )
    alternates_path = repo / ".git/objects/info/alternates"
    alternates = (
        _decode_lines(alternates_path.read_bytes())
        if alternates_path.is_file()
        else []
    )
    issues = []
    if head != base_sha:
        issues.append("HEAD differs from recorded base_sha")
    if head_sha == base_sha or merge_sha == base_sha:
        issues.append("target head/merge identity equals base_sha")
    if head_sha and head_sha != base_sha and _object_exists(repo, head_sha):
        issues.append("target head commit object is present")
    if merge_sha and merge_sha != base_sha and _object_exists(repo, merge_sha):
        issues.append("target merge commit object is present")
    if remotes:
        issues.append("Git remotes are present")
    if refs:
        issues.append("extra Git refs are present")
    if branches:
        issues.append("local branches are present")
    if tags:
        issues.append("tags are present")
    reflogs = _reflog_paths(repo)
    if reflogs:
        issues.append("reflog files are present")
    if any(commit in {head_sha, merge_sha} and commit != base_sha for commit in reachable):
        issues.append("target head/merge is reachable from HEAD")
    if worktree_status:
        issues.append("working tree is not clean")
    if alternates:
        issues.append("Git object alternates are present")
    status = "PASS" if not issues else "WARNING"
    return {
        "repository": str(repo),
        "valid_git_repository": True,
        "status": status,
        "head_sha": head,
        "tree_sha": tree,
        "head_equals_recorded_base": head == base_sha,
        "reachable_commit_count": len(reachable),
        "target_head_object_present": _object_exists(repo, head_sha),
        "target_merge_object_present": _object_exists(repo, merge_sha),
        "target_head_or_merge_reachable": any(
            commit in {head_sha, merge_sha} and commit != base_sha
            for commit in reachable
        ),
        "refs": refs,
        "branches": branches,
        "tags": tags,
        "remotes": remotes,
        "reflog_paths": reflogs,
        "shallow_repository": shallow,
        "worktree_clean": not worktree_status,
        "worktree_status": worktree_status,
        "object_alternates": alternates,
        "issues": issues,
    }


def _sanitize_repository(repo: Path) -> None:
    # Keep detached HEAD at the recorded base and remove every alternate route
    # to implementation objects.
    refs = _decode_lines(
        _git(repo, "for-each-ref", "--format=%(refname)").stdout
    )
    for ref in refs:
        _git(repo, "update-ref", "-d", ref)
    for name in _decode_lines(_git(repo, "remote").stdout):
        _git(repo, "remote", "remove", name)
    for relative in (
        "FETCH_HEAD",
        "ORIG_HEAD",
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
    ):
        (repo / ".git" / relative).unlink(missing_ok=True)
    shutil.rmtree(repo / ".git/logs", ignore_errors=True)
    shutil.rmtree(repo / ".git/refs/remotes", ignore_errors=True)
    shutil.rmtree(repo / ".git/refs/tags", ignore_errors=True)
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    _git(repo, "gc", "--prune=now")
    shutil.rmtree(repo / ".git/logs", ignore_errors=True)


def checkout_manifest(repo: Path) -> tuple[list[dict[str, Any]], str]:
    raw = _git(repo, "ls-tree", "-rz", "--full-tree", "HEAD").stdout
    entries = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        path = path_bytes.decode("utf-8", errors="surrogateescape")
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise BatchError(
                "UNSAFE_BASELINE_PATH",
                "Baseline tree contains an unsafe path",
                path=path,
            )
        content = _git(repo, "cat-file", object_type, object_id).stdout
        checkout_path = repo / path
        if mode == "120000":
            checkout_content = os.readlink(checkout_path).encode(
                "utf-8", errors="surrogateescape"
            )
        elif object_type == "blob":
            checkout_content = checkout_path.read_bytes()
        else:
            checkout_content = content
        if checkout_content != content:
            raise BatchError(
                "CHECKOUT_CONTENT_MISMATCH",
                "Checked-out file bytes differ from the recorded Git tree",
                path=path,
            )
        entries.append(
            {
                "path": path,
                "mode": mode,
                "git_type": object_type,
                "git_object": object_id,
                "size_bytes": len(content),
                "sha256": sha256_bytes(checkout_content),
            }
        )
    entries.sort(key=lambda item: item["path"])
    return entries, canonical_sha256(entries)


def _raw_record(
    raw_path: Path, *, repository: str, pr_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = []
    with raw_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BatchError(
                    "INVALID_RAW_INPUT",
                    "Raw PR input contains invalid JSON",
                    line_number=line_number,
                    error=str(exc),
                ) from exc
            if (
                isinstance(record, dict)
                and record.get("repo") == repository
                and record.get("pr_id") == pr_id
            ):
                matches.append((line_number, line.encode("utf-8"), record))
    if len(matches) != 1:
        raise BatchError(
            "RAW_RECORD_NOT_UNIQUE",
            "Expected exactly one raw record for selected PR",
            repository=repository,
            pr_id=pr_id,
            count=len(matches),
        )
    line_number, line_bytes, record = matches[0]
    return record, {
        "path": str(raw_path),
        "input_sha256": sha256_file(raw_path),
        "line_number": line_number,
        "record_line_sha256": sha256_bytes(line_bytes),
    }


def _make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            continue
        path.chmod(mode | stat.S_IWUSR)


def _make_read_only(root: Path) -> None:
    for path in [*root.rglob("*"), root]:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            continue
        path.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)


def _create_cache_repository(source: Path, destination: Path, base_sha: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{base_sha}.", dir=destination.parent)
    )
    repository = temporary / "repository"
    try:
        repository.mkdir()
        subprocess.run(
            ["git", "-C", str(repository), "init", "--quiet"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _git(
            repository,
            "fetch",
            "--quiet",
            "--depth=1",
            "--no-tags",
            str(source),
            base_sha,
        )
        _git(repository, "checkout", "--quiet", "--detach", "FETCH_HEAD")
        _sanitize_repository(repository)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _copy_workspace(cache_repo: Path, workspace_repo: Path) -> None:
    workspace_repo.parent.mkdir(parents=True, exist_ok=True)
    if workspace_repo.exists():
        raise BatchError(
            "WORKSPACE_ALREADY_EXISTS",
            "Refusing to overwrite an existing task variant workspace",
            path=str(workspace_repo),
        )
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{workspace_repo.parent.name}.", dir=workspace_repo.parent)
    )
    candidate = temporary / "repository"
    try:
        shutil.copytree(cache_repo, candidate, symlinks=True)
        _make_writable(candidate)
        _sanitize_repository(candidate)
        os.replace(candidate, workspace_repo)
        temporary.rmdir()
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _resolve_plan_path(value: str, repository_root: Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (repository_root / path).resolve()
    try:
        resolved.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise BatchError(
            "UNSAFE_PLAN_PATH",
            "Provision plan input path escapes the repository root",
            path=value,
        ) from exc
    return resolved


def _validate_provision_plan_shape(plan: Any) -> None:
    """Fail closed on plan fields that control filesystem or Git operations."""
    if not isinstance(plan, dict):
        raise BatchError("INVALID_PLAN", "Provision plan must be a JSON object")
    unknown = sorted(set(plan) - PLAN_FIELDS)
    missing = sorted(PLAN_FIELDS - set(plan))
    if unknown or missing:
        raise BatchError(
            "INVALID_PLAN_FIELDS",
            "Provision plan has unknown or missing top-level fields",
            unknown=unknown,
            missing=missing,
        )
    if plan.get("schema_version") != 1:
        raise BatchError(
            "UNKNOWN_SCHEMA_VERSION",
            "Only provision plan schema_version 1 is supported",
            found=plan.get("schema_version"),
        )
    if plan.get("plan_type") != "PROVISION_PLAN" or not ID_RE.fullmatch(
        str(plan.get("plan_id", ""))
    ):
        raise BatchError("INVALID_PLAN", "Provision plan type or plan_id is invalid")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise BatchError("INVALID_PLAN_TASKS", "Provision plan must contain tasks")
    seen_task_ids: set[str] = set()
    seen_prs: set[tuple[str, int]] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise BatchError("INVALID_PLAN_TASK", "Plan task must be an object", index=index)
        unknown = sorted(set(task) - TASK_FIELDS)
        missing = sorted(TASK_FIELDS - set(task))
        if unknown or missing:
            raise BatchError(
                "INVALID_PLAN_TASK_FIELDS",
                "Plan task has unknown or missing fields",
                index=index,
                unknown=unknown,
                missing=missing,
            )
        repository = task.get("repository")
        pr_id = task.get("pr_id")
        task_id = task.get("task_id")
        expected_task_id = (
            f"{repository.replace('/', '__')}__pr{pr_id}"
            if isinstance(repository, str)
            and isinstance(pr_id, int)
            and not isinstance(pr_id, bool)
            else None
        )
        if (
            not isinstance(task_id, str)
            or not ID_RE.fullmatch(task_id)
            or task_id != expected_task_id
        ):
            raise BatchError(
                "INVALID_TASK_ID",
                "Task ID is invalid or does not match repository and PR",
                index=index,
                task_id=task_id,
            )
        if task_id in seen_task_ids or (repository, pr_id) in seen_prs:
            raise BatchError(
                "DUPLICATE_PLAN_TASK",
                "Provision plan repeats a task",
                task_id=task_id,
            )
        seen_task_ids.add(task_id)
        seen_prs.add((repository, pr_id))
        baseline = task.get("baseline")
        if (
            not isinstance(baseline, dict)
            or set(baseline) != {"base_sha"}
            or not GIT_SHA_RE.fullmatch(str(baseline.get("base_sha", "")))
        ):
            raise BatchError(
                "INVALID_BASE_SHA",
                "Plan task recorded base_sha is invalid",
                task_id=task_id,
            )


def provision_plan(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    approved_plan_id: str,
    bench_root: Path,
    repository_root: Path,
    source_repository: Path,
) -> dict[str, Any]:
    _validate_provision_plan_shape(plan)
    if plan.get("plan_id") != approved_plan_id:
        raise BatchError(
            "PLAN_APPROVAL_MISMATCH",
            "Explicit approved plan ID does not match the plan",
            expected=plan.get("plan_id"),
            supplied=approved_plan_id,
        )
    validation = validate_plan_inputs(plan, repository_root)
    if not validation["valid"]:
        raise BatchError(
            "PLAN_INVALID",
            "Provision plan inputs are stale or invalid",
            validation=validation,
        )
    if plan.get("status") != "AWAITING_USER_APPROVAL" or plan.get("executable") is not False:
        raise BatchError(
            "PLAN_STATE_INVALID",
            "Provisioning requires a reviewed, non-executable provision plan",
        )
    if not source_repository.is_dir():
        raise BatchError(
            "BASE_SOURCE_NOT_FOUND",
            "Baseline source repository does not exist",
            path=str(source_repository),
        )
    raw_path = _resolve_plan_path(plan["inputs"]["raw"]["path"], repository_root)
    plan_sha = sha256_file(plan_path)
    report_tasks = []
    overall_warnings = False
    overall_blocked = False

    for task in plan.get("tasks", []):
        task_id = task["task_id"]
        repository = task["repository"]
        pr_id = task["pr_id"]
        planned_base = task["baseline"]["base_sha"]
        raw, raw_source = _raw_record(raw_path, repository=repository, pr_id=pr_id)
        base_sha = raw.get("base_sha")
        head_sha = raw.get("head_sha")
        merge_sha = raw.get("merge_commit_sha")
        hard_errors = []
        if not GIT_SHA_RE.fullmatch(str(base_sha or "")):
            hard_errors.append("raw record base_sha is invalid")
        if base_sha != planned_base:
            hard_errors.append("plan base_sha differs from raw recorded base_sha")
        if head_sha is not None and not GIT_SHA_RE.fullmatch(str(head_sha)):
            hard_errors.append("raw record head_sha is invalid")
        if merge_sha is not None and not GIT_SHA_RE.fullmatch(str(merge_sha)):
            hard_errors.append("raw record merge_commit_sha is invalid")
        if not _object_exists(source_repository, base_sha):
            hard_errors.append("recorded base commit is unavailable from baseline source")
        source_audit = git_topology(
            source_repository,
            base_sha=str(base_sha),
            head_sha=head_sha,
            merge_sha=merge_sha,
        )
        source_warnings = list(source_audit.get("issues", []))
        if source_audit.get("head_sha") != base_sha:
            source_warnings.append(
                "baseline source HEAD differs from recorded base; provisioning still requests recorded base explicitly"
            )

        cache_dir = bench_root / "batch/baselines" / str(base_sha)
        cache_repo = cache_dir / "repository"
        lock_path = cache_dir / "baseline-lock.json"
        cache_reused = cache_repo.exists() or lock_path.exists()
        workspace_audits = {}
        lock = None
        if not hard_errors:
            if cache_reused:
                if not cache_repo.is_dir() or not lock_path.is_file():
                    hard_errors.append("baseline cache is incomplete")
                else:
                    lock = json.loads(lock_path.read_text(encoding="utf-8"))
                    if lock.get("base_sha") != base_sha:
                        hard_errors.append("baseline cache lock base_sha mismatch")
            else:
                _create_cache_repository(source_repository, cache_dir, base_sha)
            if not hard_errors:
                cache_audit = git_topology(
                    cache_repo,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    merge_sha=merge_sha,
                )
                files, manifest_sha = checkout_manifest(cache_repo)
                if lock is None:
                    lock = {
                        "schema_version": 1,
                        "lock_type": "PURE_BASELINE",
                        "created_at_utc": _utc_now(),
                        "repository": repository,
                        "base_sha": base_sha,
                        "tree_sha": cache_audit["tree_sha"],
                        "raw_source": {
                            "path": display_path(raw_path, repository_root),
                            **{key: value for key, value in raw_source.items() if key != "path"},
                        },
                        "source_repository": {
                            "path": str(source_repository),
                            "base_object_verified": True,
                        },
                        "checkout_file_count": len(files),
                        "checkout_manifest_sha256": manifest_sha,
                        "checkout_files": files,
                        "git_topology": {
                            "head_equals_recorded_base": cache_audit["head_equals_recorded_base"],
                            "reachable_commit_count": cache_audit["reachable_commit_count"],
                            "target_head_object_present": cache_audit["target_head_object_present"],
                            "target_merge_object_present": cache_audit["target_merge_object_present"],
                            "refs": cache_audit["refs"],
                            "remotes": cache_audit["remotes"],
                            "reflog_paths": cache_audit["reflog_paths"],
                            "worktree_clean": cache_audit["worktree_clean"],
                            "object_alternates": cache_audit["object_alternates"],
                        },
                    }
                    write_json(lock_path, lock, refuse_overwrite=True)
                    _make_read_only(cache_dir)
                else:
                    if lock.get("tree_sha") != cache_audit["tree_sha"]:
                        hard_errors.append("reused baseline tree SHA mismatch")
                    if lock.get("checkout_manifest_sha256") != manifest_sha:
                        hard_errors.append("reused baseline checkout manifest mismatch")
                if cache_audit["status"] != "PASS":
                    hard_errors.extend(cache_audit["issues"])
            else:
                cache_audit = {"status": "BLOCKED", "issues": list(hard_errors)}
        else:
            cache_audit = {"status": "BLOCKED", "issues": list(hard_errors)}

        if not hard_errors:
            for variant in VARIANTS:
                workspace_repo = (
                    bench_root / "batch/workspaces" / task_id / variant / "repository"
                )
                workspace_reused = workspace_repo.exists()
                if not workspace_reused:
                    _copy_workspace(cache_repo, workspace_repo)
                elif not workspace_repo.is_dir():
                    hard_errors.append(f"{variant} workspace path is not a directory")
                    continue
                audit = git_topology(
                    workspace_repo,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    merge_sha=merge_sha,
                )
                workspace_files, workspace_manifest = checkout_manifest(workspace_repo)
                audit["checkout_file_count"] = len(workspace_files)
                audit["checkout_manifest_sha256"] = workspace_manifest
                audit["matches_baseline_tree"] = audit.get("tree_sha") == lock["tree_sha"]
                audit["matches_baseline_manifest"] = (
                    workspace_manifest == lock["checkout_manifest_sha256"]
                )
                audit["independent_workspace"] = workspace_repo.resolve() != cache_repo.resolve()
                audit["workspace_reused"] = workspace_reused
                if (
                    audit["status"] != "PASS"
                    or not audit["matches_baseline_tree"]
                    or not audit["matches_baseline_manifest"]
                ):
                    hard_errors.append(f"{variant} workspace topology verification failed")
                workspace_audits[variant] = audit

        task_status = (
            "BLOCKED"
            if hard_errors
            else "TOPOLOGY_WARNING"
            if source_warnings
            else "READY"
        )
        overall_blocked = overall_blocked or task_status == "BLOCKED"
        overall_warnings = overall_warnings or task_status == "TOPOLOGY_WARNING"
        audit_document = {
            "schema_version": 1,
            "audit_type": "HOST_ONLY_GIT_TOPOLOGY",
            "audited_at_utc": _utc_now(),
            "task_id": task_id,
            "repository": repository,
            "pr_id": pr_id,
            "status": task_status,
            "raw_topology": {
                "base_sha": base_sha,
                "head_sha": head_sha,
                "merge_commit_sha": merge_sha,
                "record_source": raw_source,
            },
            "policy": {
                "baseline_source": "raw record base_sha",
                "automatic_baseline_substitution": False,
                "agent_visibility": False,
            },
            "source_repository_audit": source_audit,
            "source_warnings": sorted(set(source_warnings)),
            "baseline_cache_audit": cache_audit,
            "variant_workspace_audits": workspace_audits,
            "blocking_errors": hard_errors,
        }
        audit_path = bench_root / "batch/audits/topology" / f"{task_id}.json"
        if audit_path.exists():
            existing_audit = json.loads(audit_path.read_text(encoding="utf-8"))
            existing_base = existing_audit.get("raw_topology", {}).get("base_sha")
            if (
                existing_audit.get("task_id") != task_id
                or existing_base != base_sha
                or existing_audit.get("status") == "BLOCKED"
                or existing_audit.get("blocking_errors")
            ):
                raise BatchError(
                    "TOPOLOGY_AUDIT_CONFLICT",
                    "Existing topology audit does not safely match this task/base",
                    path=str(audit_path),
                )
        else:
            write_json(audit_path, audit_document, refuse_overwrite=True)
        report_tasks.append(
            {
                "task_id": task_id,
                "repository": repository,
                "pr_id": pr_id,
                "status": task_status,
                "base_sha": base_sha,
                "tree_sha": lock.get("tree_sha") if lock else None,
                "baseline_cache_reused": cache_reused,
                "baseline_lock": {
                    "path": display_path(lock_path, repository_root),
                    "sha256": sha256_file(lock_path) if lock_path.is_file() else None,
                },
                "topology_audit": {
                    "path": display_path(audit_path, repository_root),
                    "sha256": sha256_file(audit_path),
                },
                "variant_workspaces": {
                    variant: display_path(
                        bench_root
                        / "batch/workspaces"
                        / task_id
                        / variant
                        / "repository",
                        repository_root,
                    )
                    for variant in workspace_audits
                },
                "blocking_errors": hard_errors,
                "warnings": sorted(set(source_warnings)),
            }
        )
    status = "BLOCKED" if overall_blocked else "TOPOLOGY_WARNING" if overall_warnings else "READY"
    return {
        "schema_version": 1,
        "report_type": "PROVISION_REPORT",
        "generated_at_utc": _utc_now(),
        "plan": {
            "plan_id": plan["plan_id"],
            "path": display_path(plan_path, repository_root),
            "sha256": plan_sha,
            "explicitly_approved_plan_id": approved_plan_id,
        },
        "status": status,
        "task_count": len(report_tasks),
        "tasks": report_tasks,
        "operations": {
            "baseline_cache_created_or_verified": True,
            "independent_variant_workspaces_created": not overall_blocked,
            "docker_images_created": False,
            "containers_created": False,
            "volumes_created": False,
            "networks_created": False,
            "agents_started": False,
            "tests_run": False,
        },
    }
