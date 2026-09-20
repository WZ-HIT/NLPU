#!/usr/bin/env python3
"""Cut a pre-experiment rollback checkpoint for a batch (pilot) task.

The checkpoints already in this directory were assembled by hand for the 8073
template task, which keeps three long-lived containers and three named HOME
volumes. A pilot task is built differently: the harness creates its containers
per run and mounts a tmpfs at ``/run/sdd-home``, so there is no container state
and no volume worth archiving. What a pilot task does keep is its bind-mounted
repository -- ``runs/<method>/detect/workspace`` -- which is precisely what SDD
mutates and precisely what a rollback has to put back.

So this captures the same *purpose* as the hand-made checkpoints in a different
*shape*: the four repositories and the deployment configuration, an explicitly
empty ``home_volumes`` list, and no Compose project of its own to restart.

Scope is drawn where the existing READMEs draw it. The checkpoint holds the
workspaces and the configuration, never ``runs/*/{executions,output,audit}``:
those are the evidence produced *after* the moment being recorded, and a
rollback that erased them would destroy the audit trail it exists to protect.

Usage:
    capture-pre-experiment.py --task scrapy__scrapy__pr8064 [--task ...]
                              [--stamp 20260919T050000Z] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BENCH_ROOT = SCRIPT_DIR.parent
TASK_ROOT = BENCH_ROOT / "tasks"

sys.path.insert(0, str(BENCH_ROOT))

from batch.core import canonical_sha256  # noqa: E402
from batch.stages import METHODS as METHOD_SPECS  # noqa: E402
from batch.stages import _file_manifest, _workspace_content_sha256  # noqa: E402

# The digest the harness itself checks before it seals. Reusing the private
# helper is deliberate: a checkpoint verified against a reimplementation of the
# gate can pass while the gate it is meant to satisfy fails.
METHODS = ("openspec", "speckit", "cc-sdd")

# Task-directory members that are deployment configuration rather than
# experiment evidence. ``runs/`` is excluded on purpose -- see the module
# docstring.
CONFIG_EXCLUDES = {"runs"}


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, **kwargs)


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout.decode(errors="replace").strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_tree(source: Path, destination: Path) -> None:
    """Tar a directory's *contents*, deterministically at the gzip layer.

    ``tarfile`` writes a stream gzip cannot be asked to stamp as ``-n``, so the
    header timestamp is zeroed afterwards. Without that, two checkpoints cut
    seconds apart from the same baseline tree are byte-different and cannot be
    hardlinked -- and the baseline tree is shared by every task on a base SHA.
    """
    with tempfile.TemporaryDirectory(prefix="sdd-precheckpoint-") as temporary:
        raw = Path(temporary) / "payload.tar"
        with tarfile.open(raw, "w") as tar:
            for entry in sorted(source.iterdir()):
                tar.add(entry, arcname=entry.name, recursive=True)
        with raw.open("rb") as reader, destination.open("wb") as writer:
            with gzip.GzipFile(fileobj=writer, mode="wb", mtime=0) as compressor:
                shutil.copyfileobj(reader, compressor)


def archive_members(bench: Path, members: list[str], destination: Path) -> None:
    """Tar an explicit list of repository-relative paths, holding the tree."""
    with tempfile.TemporaryDirectory(prefix="sdd-precheckpoint-") as temporary:
        raw = Path(temporary) / "payload.tar"
        with tarfile.open(raw, "w") as tar:
            for member in members:
                tar.add(bench / member, arcname=member, recursive=True)
        with raw.open("rb") as reader, destination.open("wb") as writer:
            with gzip.GzipFile(fileobj=writer, mode="wb", mtime=0) as compressor:
                shutil.copyfileobj(reader, compressor)


def configuration_members(task_dir: Path) -> list[str]:
    """Every top-level entry of the task directory except the evidence tree."""
    task_id = task_dir.name
    return sorted(
        f"tasks/{task_id}/{entry.name}"
        for entry in task_dir.iterdir()
        if entry.name not in CONFIG_EXCLUDES
    )


def detect_mount_path(task_dir: Path, method: str) -> Path:
    """Detect's Compose bind source for one method's planning artifacts.

    The rendered Compose sets ``create_host_path: false`` on this bind, so a
    missing directory is not created empty -- the container is not created at
    all. Scaffolding makes it, empty, at task creation and the harness never
    recreates it, so it is part of the state a rollback has to put back.
    """
    return task_dir / "runs" / method / "detect" / "planning-artifacts"


def seal_path(task_dir: Path, method: str) -> Path:
    """The Detect seal. Its existence is one-way: a second Detect refuses."""
    return task_dir / "runs" / method / "update" / "sealed-input"


def _scaffold_placeholder(entry: dict[str, Any]) -> bool:
    """True for the empty-directory marker ``scaffold`` writes into the mount.

    ``scaffold`` leaves openspec's planning mount non-empty on purpose: it
    drops a zero-byte ``archive/.gitkeep`` so the archive directory survives
    being copied. Reading that file as Detect output would make every openspec
    task uncapturable, so the pre-Detect gate looks past it. The counts this
    module records in ``checkpoint.json`` are left alone -- those should
    describe the mount exactly as it was found.
    """
    return entry["path"].endswith("/.gitkeep") and entry["size_bytes"] == 0


def repository_record(name: str, path: Path, payload: str) -> dict[str, Any]:
    """Git identity of one repository, in the shape the existing checkpoints use."""
    branch = git(path, "branch", "--show-current")
    porcelain = git(path, "status", "--porcelain").splitlines()
    untracked = sorted({line[3:].split("/")[0] + ("/" if "/" in line[3:] else "") for line in porcelain if line.startswith("??")})
    tracked_dirty = [line for line in porcelain if not line.startswith("??")]
    return {
        # A pilot workspace is left on a detached HEAD: the harness pins the
        # base SHA rather than a branch name, so an empty branch is the norm and
        # is recorded as such rather than reported as a missing value.
        "name": name,
        "branch": branch or None,
        "detached": not branch,
        "head": git(path, "rev-parse", "HEAD"),
        "reachable_commit_count": int(git(path, "rev-list", "--count", "HEAD") or 0),
        "remote_count": len([line for line in git(path, "remote").splitlines() if line]),
        "tracked_worktree_clean": not tracked_dirty,
        "untracked_file_count": len([line for line in porcelain if line.startswith("??")]),
        "untracked_roots": untracked,
        "payload": payload,
    }


def docker_image_id(reference: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        die(f"required image is not present locally: {reference}")
    return result.stdout.decode().strip()


class PayloadLedger:
    """Deduplicate byte-identical payloads across checkpoints by hardlink.

    Two pilot tasks on the same base SHA share both their baseline repository
    and their agent image, and an image archive is ~350 MB. The existing
    checkpoints already share payloads this way (the Pro and Flash 8073
    checkpoints hardlink every file they have in common), so this follows the
    convention rather than inventing one.
    """

    def __init__(self) -> None:
        self.by_digest: dict[str, Path] = {}

    def register(self, name: str, staged: Path, destination_dir: Path) -> str:
        digest = sha256_file(staged)
        destination = destination_dir / name
        existing = self.by_digest.get(digest)
        if existing is not None and existing.exists():
            os.link(existing, destination)
        else:
            shutil.move(str(staged), str(destination))
            self.by_digest[digest] = destination
        return digest


def capture(
    task_id: str,
    stamp: str,
    ledger: PayloadLedger,
    image_cache: dict[tuple[str, str], Path],
    dry_run: bool,
) -> str:
    task_dir = TASK_ROOT / task_id
    if not task_dir.is_dir():
        die(f"no such task directory: {task_dir}")

    lock_path = task_dir / "initial-workspaces.json"
    if not lock_path.is_file():
        die(f"task has no frozen initial workspaces: {lock_path}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))

    # Refuse to record a state that has already drifted. A checkpoint of a
    # modified workspace is worse than none: it looks like a rollback point and
    # would restore code SDD has already touched.
    #
    # Being *before Detect* is the same kind of claim, and is measured rather
    # than asserted: an empty mount point and no seal is what a task looks like
    # before Detect runs, and either fact being otherwise means it has run.
    # Capturing then would record Detect's own output as the starting state.
    drifted: list[str] = []
    already_run: list[str] = []
    planning_records: list[dict[str, Any]] = []
    for entry in lock["workspaces"]:
        method = entry["method"]
        workspace = task_dir / entry["detect_workspace"]
        if not workspace.is_dir():
            die(f"workspace is missing: {workspace}")
        if _workspace_content_sha256(workspace) != entry["initial_workspace_sha256"]:
            drifted.append(method)

        mount = detect_mount_path(task_dir, method)
        if not mount.is_dir():
            die(
                "refusing to capture: the Detect bind source is missing, so a "
                f"restore would have nothing to record: {mount}"
            )
        entries, manifest_sha = _file_manifest(mount)
        planning_records.append(
            {
                "method": method,
                "path": f"runs/{method}/detect/planning-artifacts",
                "container_mount": METHOD_SPECS[method]["planning_mount_path"],
                "file_count_at_capture": len(entries),
                "manifest_sha256_at_capture": manifest_sha,
                "empty_at_capture": not entries,
            }
        )
        if [entry for entry in entries if not _scaffold_placeholder(entry)]:
            already_run.append(f"{method} (planning artifacts written)")
        if seal_path(task_dir, method).exists():
            already_run.append(f"{method} (already sealed)")

    if drifted:
        die(
            "refusing to capture: these detect workspaces differ from their "
            f"frozen initial state: {', '.join(drifted)}"
        )
    if already_run:
        die(
            "refusing to capture: this task is not in its pre-Detect state: "
            f"{', '.join(already_run)}"
        )

    slug = f"pr{lock.get('pr_id') or task_id.rsplit('pr', 1)[-1]}"
    checkpoint_id = f"pre-experiment-{slug}-{stamp}"
    checkpoint_dir = SCRIPT_DIR / checkpoint_id
    if checkpoint_dir.exists():
        die(f"checkpoint already exists: {checkpoint_dir}")

    print(f"=== {checkpoint_id}")
    print(f"    task     {task_id}")
    print(f"    base_sha {lock['base_sha']}")

    if dry_run:
        print("    DRY: would archive baseline + 3 workspaces + config + images")
        return checkpoint_id

    payloads = checkpoint_dir / "payloads"
    payloads.mkdir(parents=True)
    staged_dir = Path(tempfile.mkdtemp(prefix="sdd-precheckpoint-stage-"))
    sums: list[tuple[str, str]] = []

    try:
        # 1. The immutable baseline: the pre-merge Scrapy tree every method
        #    branches from. Shared by every task on this base SHA.
        baseline = BENCH_ROOT / "batch" / "baselines" / lock["base_sha"] / "repository"
        if not baseline.is_dir():
            die(f"baseline repository is missing: {baseline}")
        staged = staged_dir / "baseline-repo.tar.gz"
        archive_tree(baseline, staged)
        sums.append((ledger.register("baseline-repo.tar.gz", staged, payloads), "baseline-repo.tar.gz"))

        # 2. One repository per method: the bind mount the container sees as
        #    /workspace, at the exact state the harness will later re-verify.
        repositories = [
            repository_record("baseline", baseline, "baseline-repo.tar.gz")
        ]
        for method in METHODS:
            workspace = task_dir / "runs" / method / "detect" / "workspace"
            if not workspace.is_dir():
                die(f"detect workspace is missing: {workspace}")
            name = f"{method}-repo.tar.gz"
            staged = staged_dir / name
            archive_tree(workspace, staged)
            sums.append((ledger.register(name, staged, payloads), name))
            repositories.append(repository_record(method, workspace, name))

        # 3. Deployment configuration. Everything in the task directory except
        #    the evidence tree under runs/.
        staged = staged_dir / "deployment-config.tar.gz"
        archive_members(BENCH_ROOT, configuration_members(task_dir), staged)
        sums.append((ledger.register("deployment-config.tar.gz", staged, payloads), "deployment-config.tar.gz"))

        # 4. Offline images, so a pruned Docker cache cannot strand a rollback.
        deployment_lock = json.loads(
            (task_dir / "compose-deployment-lock.json").read_text(encoding="utf-8")
        )
        agent_image_id = deployment_lock["images"]["agent_image_id"]
        proxy_image_id = deployment_lock["images"]["proxy_image_id"]
        key = (agent_image_id, proxy_image_id)
        cached = image_cache.get(key)
        staged = staged_dir / "deployment-images.tar.gz"
        if cached is not None and cached.exists():
            # Hardlinked from the first checkpoint cut in this run rather than
            # saved again: `docker save` is not guaranteed to emit the same
            # bytes twice, so the digest ledger alone would not deduplicate it.
            os.link(cached, staged)
        else:
            with staged.open("wb") as handle:
                run(
                    ["docker", "save", agent_image_id, proxy_image_id],
                    stdout=handle,
                    stderr=subprocess.DEVNULL,
                )
        sums.append(
            (ledger.register("deployment-images.tar.gz", staged, payloads), "deployment-images.tar.gz")
        )
        image_cache[key] = payloads / "deployment-images.tar.gz"

        (payloads / "SHA256SUMS").write_text(
            "".join(f"{digest}  {name}\n" for digest, name in sorted(sums)), encoding="utf-8"
        )
    finally:
        shutil.rmtree(staged_dir, ignore_errors=True)

    document = {
        "schema_version": 1,
        "checkpoint_id": checkpoint_id,
        "created_at_utc": datetime.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": (
            f"Rollback point for batch task {task_id} on Scrapy base "
            f"{lock['base_sha'][:7]}, taken before any SDD stage ran"
        ),
        "task_id": task_id,
        "pr_id": lock.get("pr_id"),
        "task_base_sha": lock["base_sha"],
        "task_base_tree": lock.get("tree_sha"),
        "repositories": repositories,
        # A pilot task's HOME is a tmpfs at /run/sdd-home, torn down with the
        # container. There is no volume to archive, and an empty list is the
        # honest record of that -- not an omission.
        "home_volumes": [],
        "home_kind": "tmpfs:/run/sdd-home",
        # Detect's Compose bind source is recorded, not packaged: it holds no
        # bytes at this moment, and an empty tar would carry none. What a
        # restore needs from it is the fact that the directory belongs there at
        # all -- Compose renders the bind with ``create_host_path: false``, so
        # without it the Detect container is not created *empty*, it is not
        # created. ``file_count_at_capture`` is therefore always 0; it is
        # written out rather than assumed so that a checkpoint recording
        # anything else is visibly wrong rather than silently plausible.
        "detect_planning_artifacts": planning_records,
        "initial_workspaces": [
            {
                "method": entry["method"],
                "detect_workspace": entry["detect_workspace"],
                "initial_workspace_sha256": entry["initial_workspace_sha256"],
                "workspace_file_count": entry["workspace_file_count"],
                "update_workspace_created": entry.get("update_workspace_created"),
            }
            for entry in lock["workspaces"]
        ],
        "deployment": {
            # The harness substitutes a project name per run, so there is no
            # single literal project to record; the prefix is what a restore
            # needs in order to find and stop whatever is live.
            "compose_project": None,
            "compose_project_template": "${COMPOSE_PROJECT_NAME}",
            "compose_project_prefix": task_id.replace("__", "-") + "-",
            "agent_image": f"scrapy-sdd-batch-agent:{lock['base_sha']}",
            "agent_image_id": agent_image_id,
            "proxy_image": "haproxy:3.2.23-alpine3.24",
            "proxy_image_id": proxy_image_id,
            "agent_container_count": 0,
            "container_lifetime": "per-run",
            "configuration_members": configuration_members(task_dir),
            "configuration_payload": "deployment-config.tar.gz",
            "offline_image_payload": "deployment-images.tar.gz",
            "deployment_lock_sha256": sha256_file(task_dir / "compose-deployment-lock.json"),
        },
        "parent_repository": {
            "branch": git(BENCH_ROOT, "branch", "--show-current"),
            "commit": git(BENCH_ROOT, "rev-parse", "--short", "HEAD"),
        },
        # The digest describes the state this checkpoint restores *to*, not the
        # bytes it carries, so the mount points are part of it: a restore that
        # recreates them lands somewhere different from one that does not.
        # Checkpoints cut before this field existed are not comparable against
        # this formula, which is acceptable because nothing verifies the digest
        # -- verify.sh checks payload bytes and the join between metadata and
        # payloads instead.
        "content_sha256": canonical_sha256(
            {
                "task_id": task_id,
                "task_base_sha": lock["base_sha"],
                "initial_workspaces": sorted(
                    (entry["method"], entry["initial_workspace_sha256"])
                    for entry in lock["workspaces"]
                ),
                "detect_planning_artifacts": sorted(
                    (record["method"], record["manifest_sha256_at_capture"])
                    for record in planning_records
                ),
                "configuration_members": configuration_members(task_dir),
                "payloads": sorted(sums),
            }
        ),
        "payload_total_bytes": sum((payloads / name).stat().st_size for _, name in sums),
        "contains_api_secret": False,
        "experiment_logs_included": False,
    }
    (checkpoint_dir / "checkpoint.json").write_text(
        json.dumps(document, indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for template in ("verify.sh", "restore.sh"):
        target = checkpoint_dir / template
        shutil.copyfile(SCRIPT_DIR / "templates" / template, target)
        target.chmod(0o755)
    shutil.copyfile(SCRIPT_DIR / "templates" / "README.md", checkpoint_dir / "README.md")

    print(f"    payloads {document['payload_total_bytes'] / 1e6:.1f} MB")
    print(f"checkpoint_captured={checkpoint_id}")
    return checkpoint_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", default=[], help="task id (repeatable)")
    parser.add_argument("--stamp", default=None, help="UTC stamp, e.g. 20260919T050000Z")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    if not arguments.task:
        die("at least one --task is required")

    stamp = arguments.stamp or datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    ledger = PayloadLedger()
    image_cache: dict[tuple[str, str], Path] = {}
    captured = [
        capture(task_id, stamp, ledger, image_cache, arguments.dry_run)
        for task_id in arguments.task
    ]
    print(f"\ncapture_complete count={len(captured)} stamp={stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
