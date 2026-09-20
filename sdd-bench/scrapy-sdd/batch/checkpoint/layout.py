"""Checkpoint layout, payload inclusion rules, and regenerability assertions.

This module holds the shared vocabulary for the batch checkpoint device: where a
layer lives on disk, which paths belong in a payload, and how to prove that an
excluded directory can be rebuilt. It deliberately performs no capture, verify,
or restore work of its own.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import stat
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..core import BatchError, sha256_bytes, sha256_file

CHECKPOINT_ROOT = "checkpoints/batch"
SHARED_NAME = "shared"
PR_NAME = "pr"
PAYLOAD_DIRNAME = "payloads"
BACKUP_DIRNAME = "restore-backups"
CHECKPOINT_FILE = "checkpoint.json"
SUMS_FILE = "SHA256SUMS"
FILES_SUFFIX = ".files.sha256"

TASKS_DIRNAME = "tasks"
GOLD_DIRNAME = "batch/gold"
DEFAULT_BATCH_RUNS = "batch/runs"
DEFAULT_BASELINES = "batch/baselines"
DEFAULT_IMAGES = "batch/images"

# Tracked configuration that ships in Git. These are recorded and re-verified
# rather than packaged, exactly like the raw dataset inputs. The two lists have
# different bases: the deployment config lives inside the bench, the dataset
# inputs live at the repository root. Each list declares the base its paths are
# written against, and `tracked_input_rows` rebases them onto the repository
# root, which is what Git and the checkpoint metadata both speak.
BENCH_TRACKED_DEPLOYMENT_CONFIG = (
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/config.toml",
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/deepseek-flash.config.toml",
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/deepseek-v4-pro.config.toml",
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-flash/models.json",
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-v4-pro/models.json",
    "environments/network/haproxy-3.2.23/deepseek-tls-egress.cfg",
)

REPOSITORY_TRACKED_RAW_INPUTS = (
    "output/prompt/scrapy__scrapy.json",
    "output/raw_prs/scrapy__scrapy.jsonl",
)

SKIP_NAMES = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = (".lock",)


def api_key_path() -> Path:
    """The preflight credential path. Never opened, only existence-checked."""
    return Path.home() / ".config/sdd-bench/deepseek-api-key"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def checkpoint_root(bench: Path) -> Path:
    return bench / CHECKPOINT_ROOT


def shared_dir(bench: Path) -> Path:
    return checkpoint_root(bench) / SHARED_NAME


def pr_dir(bench: Path, task_id: str) -> Path:
    return checkpoint_root(bench) / PR_NAME / task_id


def pr_root(bench: Path) -> Path:
    return checkpoint_root(bench) / PR_NAME


def backups_dir(bench: Path) -> Path:
    return checkpoint_root(bench) / BACKUP_DIRNAME


def payload_dir(layer: Path) -> Path:
    return layer / PAYLOAD_DIRNAME


def checkpoint_path(layer: Path) -> Path:
    return layer / CHECKPOINT_FILE


def payload_path(layer: Path, name: str) -> Path:
    return payload_dir(layer) / name


def files_manifest_path(layer: Path, name: str) -> Path:
    return payload_dir(layer) / (name + FILES_SUFFIX)


def default_batch_id(bench: Path) -> str:
    """The batch run directory a checkpointed task currently belongs to."""
    runs = bench / DEFAULT_BATCH_RUNS
    if not runs.is_dir():
        return ""
    candidates = sorted(path.name for path in runs.iterdir() if (path / "ledger.jsonl").is_file())
    return candidates[0] if len(candidates) == 1 else ""


def make_private(path: Path, *, directory: bool) -> None:
    """Checkpoint metadata and payloads can embed gold content; keep them 0700/0600."""
    try:
        path.chmod(0o700 if directory else 0o600)
    except FileNotFoundError:
        pass


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    make_private(path, directory=True)
    return path


def task_ids(bench: Path) -> list[str]:
    root = bench / TASKS_DIRNAME
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and entry.name.startswith("scrapy__scrapy__pr")
    )


def task_root(bench: Path, task_id: str) -> Path:
    if not task_id.startswith("scrapy__scrapy__") or "/" in task_id or ".." in task_id:
        raise BatchError(
            "INVALID_TASK_ID", "Task id must be a scrapy__scrapy__* directory name", task_id=task_id
        )
    return bench / TASKS_DIRNAME / task_id


# --------------------------------------------------------------------------
# Exclusion rules
# --------------------------------------------------------------------------


def excluded_reason(parts: tuple[str, ...]) -> str | None:
    """Why a task-relative directory is not part of the payload, or None.

    This is a deny-list, not an allow-list: anything that is not a workspace or
    Git metadata is packaged, so a new evidence type can never be dropped
    silently. Every match here must carry a regenerability assertion.
    """
    if ".git" in parts:
        return "git-metadata"
    if len(parts) == 4 and parts[0] == "runs" and parts[2] == "detect" and parts[3] == "workspace":
        return "detect-workspace"
    if (
        len(parts) == 8
        and parts[0] == "runs"
        and parts[2] == "update"
        and parts[3] == "executions"
        and parts[5].startswith("attempt-")
        and parts[6].startswith("mode-")
        and parts[7] == "workspace"
    ):
        return "update-workspace"
    return None


@dataclass(frozen=True)
class ExcludedDir:
    relative: str
    reason: str
    file_count: int
    size_bytes: int
    assertion: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.relative,
            "reason": self.reason,
            "file_count": self.file_count,
            "size_bytes": self.size_bytes,
            "assertion": self.assertion,
        }


def _measure(root: Path) -> tuple[int, int]:
    count = 0
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for entry in entries:
            if entry.is_symlink():
                count += 1
                try:
                    total += entry.lstat().st_size
                except OSError:
                    pass
            elif entry.is_dir():
                stack.append(entry)
            else:
                count += 1
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    return count, total


def walk_tree(
    root: Path, *, skip_names: Iterable[str] = (), skip_suffixes: Iterable[str] = ()
) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]]]:
    """Split a tree into (kept, skipped) path lists, never following symlinks."""
    skip_name_set = set(skip_names)
    skip_suffix_tuple = tuple(skip_suffixes)
    kept: list[tuple[str, Path]] = []
    skipped: list[tuple[str, Path]] = []
    stack: list[tuple[tuple[str, ...], Path]] = [((), root)]
    while stack:
        parts, current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for entry in entries:
            child = parts + (entry.name,)
            if entry.is_symlink():
                kept.append(("/".join(child), entry))
            elif entry.is_dir():
                if entry.name in skip_name_set:
                    skipped.append(("/".join(child), entry))
                else:
                    stack.append((child, entry))
            elif entry.name.endswith(skip_suffix_tuple):
                skipped.append(("/".join(child), entry))
            else:
                kept.append(("/".join(child), entry))
    kept.sort(key=lambda item: item[0])
    skipped.sort(key=lambda item: item[0])
    return kept, skipped


def walk_task_payload(root: Path) -> tuple[list[tuple[str, Path]], list[ExcludedDir]]:
    """Payload entries under a task directory plus the excluded workspaces."""
    kept: list[tuple[str, Path]] = []
    excluded: list[ExcludedDir] = []
    stack: list[tuple[tuple[str, ...], Path]] = [((), root)]
    while stack:
        parts, current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for entry in entries:
            child = parts + (entry.name,)
            relative = "/".join(child)
            if entry.is_symlink():
                kept.append((relative, entry))
            elif entry.is_dir():
                reason = excluded_reason(child)
                if reason is None:
                    stack.append((child, entry))
                else:
                    count, size = _measure(entry)
                    excluded.append(ExcludedDir(relative, reason, count, size, ""))
            else:
                kept.append((relative, entry))
    kept.sort(key=lambda item: item[0])
    excluded.sort(key=lambda item: item.relative)
    return kept, excluded


# --------------------------------------------------------------------------
# Manifests
# --------------------------------------------------------------------------


def manifest_lines(entries: Iterable[tuple[str, Path]]) -> tuple[list[str], str]:
    """`sha256sum --check --strict` lines for explicit (relative, path) pairs.

    Symlinks are hashed through ``os.readlink`` (the link target string), which
    matches ``gold_audit.file_manifest`` and never dereferences out of the tree.
    """
    lines = []
    for relative, path in entries:
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8", errors="surrogateescape")
        else:
            data = path.read_bytes()
        lines.append(f"{sha256_bytes(data)}  {relative}")
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    return lines, sha256_bytes(payload)


def parse_manifest(text: str) -> list[tuple[str, str]]:
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, _, relative = line.partition("  ")
        if len(digest) != 64 or not relative:
            raise BatchError("MANIFEST_MALFORMED", "File manifest line is malformed", line=line[:200])
        entries.append((digest, relative))
    return entries


def check_manifest(root: Path, text: str) -> None:
    """Re-derive every hash in a manifest against the tree under ``root``."""
    missing = []
    mismatched = []
    for digest, relative in parse_manifest(text):
        path = root / relative
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8", errors="surrogateescape")
        elif path.is_file():
            data = path.read_bytes()
        else:
            missing.append(relative)
            continue
        if sha256_bytes(data) != digest:
            mismatched.append(relative)
    if missing or mismatched:
        raise BatchError(
            "MANIFEST_MISMATCH",
            "Files do not match the recorded manifest",
            missing=sorted(missing)[:20],
            mismatched=sorted(mismatched)[:20],
        )


# --------------------------------------------------------------------------
# Payload archives
# --------------------------------------------------------------------------


def write_payload(
    destination: Path, entries: list[tuple[str, Path]], *, arc_prefix: str
) -> dict[str, Any]:
    """Write one tar.gz payload plus its sidecar file manifest."""
    ensure_private_dir(destination.parent)
    lines, manifest_sha = manifest_lines(entries)
    with tarfile.open(destination, "w:gz", compresslevel=6, format=tarfile.PAX_FORMAT) as archive:
        for relative, path in entries:
            info = archive.gettarinfo(str(path), arcname=f"{arc_prefix}/{relative}")
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            if info.isfile():
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            else:
                archive.addfile(info)
    make_private(destination, directory=False)
    manifest_path = files_manifest_path(destination.parent.parent, destination.name)
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    make_private(manifest_path, directory=False)
    return {
        "name": destination.name,
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        "member_count": len(entries),
        "file_manifest_sha256": manifest_sha,
    }


def read_payload_manifest(layer: Path, name: str) -> str:
    path = files_manifest_path(layer, name)
    if not path.is_file():
        raise BatchError(
            "PAYLOAD_MANIFEST_MISSING",
            "Payload is missing its file manifest sidecar",
            path=str(path),
        )
    return path.read_text(encoding="utf-8")


def extract_payload(layer: Path, name: str, destination: Path) -> None:
    path = payload_path(layer, name)
    if not path.is_file():
        raise BatchError("PAYLOAD_MISSING", "Payload archive is missing", path=str(path))
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "r:gz") as archive:
        archive.extractall(destination, filter="data")


def write_sums(layer: Path, payloads: list[dict[str, Any]]) -> None:
    lines = [
        f"{item['sha256']}  {PAYLOAD_DIRNAME}/{item['name']}"
        for item in sorted(payloads, key=lambda entry: entry["name"])
    ]
    path = layer / SUMS_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    make_private(path, directory=False)


def read_sums(layer: Path) -> list[tuple[str, str]]:
    path = layer / SUMS_FILE
    if not path.is_file():
        raise BatchError("SUMS_MISSING", "Checkpoint is missing SHA256SUMS", path=str(path))
    return parse_manifest(path.read_text(encoding="utf-8"))


def payload_sizes(payloads: list[dict[str, Any]]) -> int:
    return sum(int(item["size_bytes"]) for item in payloads)


# --------------------------------------------------------------------------
# Git-backed regenerability assertions
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )


def git_head(repo: Path) -> str:
    result = _git(repo, "rev-parse", "HEAD")
    if result.returncode:
        raise BatchError(
            "WORKSPACE_GIT_FAILED",
            "Cannot read HEAD from an excluded workspace",
            path=str(repo),
            stderr=result.stderr.decode(errors="replace")[-1500:],
        )
    return result.stdout.decode().strip()


def git_status(repo: Path) -> list[tuple[str, str]]:
    """(status code, path) pairs, NUL separated so quoting never hides a path."""
    result = _git(repo, "status", "--porcelain=v1", "-z", "-uall")
    if result.returncode:
        raise BatchError(
            "WORKSPACE_GIT_FAILED",
            "git status failed inside an excluded workspace",
            path=str(repo),
            stderr=result.stderr.decode(errors="replace")[-1500:],
        )
    fields = result.stdout.split(b"\0")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if not record:
            continue
        code = record[:2].decode("ascii", errors="replace")
        relative = record[3:].decode("utf-8", errors="surrogateescape")
        entries.append((code, relative))
        if "R" in code or "C" in code:
            # A rename record carries its original path as the next NUL field.
            index += 1
    return entries


def initialization_roots(task: Path, method: str) -> list[str]:
    root = task / "initialization" / method / "files"
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir())


def under_initialization(relative: str, roots: list[str]) -> bool:
    return any(relative == root or relative.startswith(root + "/") for root in roots)


def patch_paths(patch: Path) -> set[str]:
    if not patch.is_file():
        return set()
    found = set()
    for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("--- ", "+++ ", "diff --git ")):
            continue
        for token in line.split():
            if token.startswith(("a/", "b/")):
                found.add(token[2:])
    return found


def assert_detect_workspace(
    *, workspace: Path, method: str, base_sha: str, task: Path, label: str
) -> str:
    """Prove a Detect workspace is baseline + initialization only."""
    problems = []
    if not workspace.is_dir():
        problems.append(f"{label}: workspace directory is missing")
    else:
        head = git_head(workspace)
        if head != base_sha:
            problems.append(f"{label}: HEAD {head} differs from recorded base {base_sha}")
        roots = initialization_roots(task, method)
        for code, relative in git_status(workspace):
            if code != "??":
                problems.append(
                    f"{label}/{relative}: tracked file was modified in the Detect workspace"
                )
            elif not under_initialization(relative, roots):
                problems.append(
                    f"{label}/{relative}: untracked path is not under "
                    f"initialization/{method}/files"
                )
    if problems:
        raise BatchError(
            "WORKSPACE_NOT_REGENERABLE",
            "Excluded Detect workspace holds content that cannot be rebuilt",
            workspace=str(workspace),
            excluded_path=label,
            problems=problems[:20],
        )
    return f"HEAD=={base_sha}, untracked paths under initialization/{method}/files"


def assert_update_workspace(*, workspace: Path, method: str, task: Path, label: str) -> str:
    """Prove an Update workspace is initialization + its own candidate.patch."""
    problems = []
    if not workspace.is_dir():
        problems.append(f"{label}: workspace directory is missing")
    else:
        roots = initialization_roots(task, method)
        explained = patch_paths(workspace.parent / "artifacts" / "candidate.patch")
        for code, relative in git_status(workspace):
            if code == "??":
                if not under_initialization(relative, roots):
                    problems.append(
                        f"{label}/{relative}: untracked path is not under "
                        f"initialization/{method}/files"
                    )
            elif relative not in explained:
                problems.append(
                    f"{label}/{relative}: modified file is absent from "
                    "artifacts/candidate.patch"
                )
    if problems:
        raise BatchError(
            "WORKSPACE_NOT_REGENERABLE",
            "Excluded Update workspace holds content that cannot be rebuilt",
            workspace=str(workspace),
            excluded_path=label,
            problems=problems[:20],
        )
    return "tracked modifications all present in artifacts/candidate.patch"


def assert_excluded_workspaces(
    *, task: Path, method: str, base_sha: str, excluded: list[ExcludedDir]
) -> list[ExcludedDir]:
    """Attach a passing regenerability assertion to every excluded workspace."""
    asserted = []
    for item in excluded:
        workspace = task / item.relative
        if item.reason == "detect-workspace":
            assertion = assert_detect_workspace(
                workspace=workspace, method=method, base_sha=base_sha, task=task, label=item.relative
            )
        elif item.reason == "update-workspace":
            assertion = assert_update_workspace(
                workspace=workspace, method=method, task=task, label=item.relative
            )
        else:
            assertion = "Git metadata only"
        asserted.append(
            ExcludedDir(item.relative, item.reason, item.file_count, item.size_bytes, assertion)
        )
    return asserted


# --------------------------------------------------------------------------
# Tracked inputs and run barriers
# --------------------------------------------------------------------------


def track_tracked_input(repository_root: Path, relative: str) -> dict[str, Any]:
    """Record a Git-tracked file instead of packaging it.

    Tracked-and-clean means Git can restore the exact bytes, which is why the
    raw dataset inputs and the tracked deployment config cost no payload space.
    """
    path = repository_root / relative
    if not path.is_file():
        raise BatchError("TRACKED_INPUT_MISSING", "Tracked input is missing", path=relative)
    recorded = {}
    blob = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", f"HEAD:{relative}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    tracked = blob.returncode == 0
    if tracked:
        recorded["git_blob_sha"] = blob.stdout.decode().strip()
    head = subprocess.run(
        ["git", "-C", str(repository_root), "show", f"HEAD:{relative}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    head_bytes = head.stdout if head.returncode == 0 else b""
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "tracked": tracked,
        "git_blob_sha": recorded.get("git_blob_sha"),
        "worktree_matches_head": tracked and head_bytes == path.read_bytes(),
    }


def repository_relative(bench: Path, repository_root: Path, relative: str) -> str:
    """Rebase a bench-relative path onto the repository root."""
    resolved = (bench / relative).resolve()
    try:
        return resolved.relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        raise BatchError(
            "BENCH_OUTSIDE_REPOSITORY",
            "The bench is not inside the repository root, so a bench-relative "
            "path cannot be expressed repository-relative",
            bench=str(bench),
            repository_root=str(repository_root),
            path=relative,
        ) from None


def tracked_input_rows(
    bench: Path, repository_root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The (raw_inputs, deployment_config) rows, all repository-root-relative."""
    raw_inputs = [
        track_tracked_input(repository_root, item) for item in REPOSITORY_TRACKED_RAW_INPUTS
    ]
    deployment_config = [
        track_tracked_input(repository_root, repository_relative(bench, repository_root, item))
        for item in BENCH_TRACKED_DEPLOYMENT_CONFIG
    ]
    return raw_inputs, deployment_config


def run_lock_holders(bench: Path) -> list[str]:
    """Batch ids whose orchestrate run-duration lock is currently held."""
    holders = []
    runs = bench / DEFAULT_BATCH_RUNS
    if not runs.is_dir():
        return holders
    for lock in sorted(runs.glob("*/run.lock")):
        if not lock.exists():
            continue
        try:
            handle = os.open(lock, os.O_RDWR)
        except OSError:
            continue
        try:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                holders.append(lock.parent.name)
        finally:
            os.close(handle)
    return holders


def running_compose_projects(prefix: str) -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "--format", '{{.Label "com.docker.compose.project"}}'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        return []
    names = {line.strip() for line in result.stdout.decode(errors="replace").splitlines()}
    return sorted(name for name in names if name and name.startswith(prefix))


def compose_project_prefix(task_id: str) -> str:
    """Task id -> the Docker Compose project prefix built by batch/stages.py."""
    return task_id.replace("__", "-") + "-"


# --------------------------------------------------------------------------
# Restore-time safety backups
# --------------------------------------------------------------------------


def backup_paths(bench: Path, stamp: str, *relative: str) -> Path:
    root = backups_dir(bench) / stamp
    for part in relative:
        root = root / part
    return root


def move_aside(source: Path, destination: Path) -> None:
    """Relocate existing state instead of deleting it; the device never rm -rf's."""
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise BatchError(
            "BACKUP_COLLISION", "Restore backup destination already exists", path=str(destination)
        )
    shutil.move(str(source), str(destination))


def make_writable(root: Path) -> None:
    """Baseline caches are sealed read-only; restore has to replace them."""
    if not root.exists():
        return
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        try:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        except FileNotFoundError:
            pass
