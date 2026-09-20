"""Restore captured checkpoint layers.

Restore is deliberately non-destructive with respect to *files*: whatever it
replaces is moved into ``checkpoints/batch/restore-backups/<UTC>/`` rather than
removed.

Docker objects are not handled here. Files are only half of a task's live state,
so a restore that leaves containers behind has not returned the task to the
state the checkpoint recorded -- but the batch harness tears its own stacks down
in a ``finally``, so on the normal path there is nothing left to clear. A task
whose stack is still up is therefore taken as evidence that something is wrong,
and the restore refuses rather than proceeding over it.

The command refuses to run while a batch holds its run lock. Unlike the legacy
template device it never starts a container and never opens the preflight
credential.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..core import BatchError, sha256_file
from . import layout
from .verify import _verify_payloads, verify_pr, verify_shared


def _assert_required(yes: bool) -> None:
    if not yes:
        raise BatchError(
            "RESTORE_CONFIRMATION_REQUIRED",
            "Restore replaces live experiment state; re-run with --yes to confirm",
        )


def _assert_quiescent(bench: Path, *, task_id: str | None) -> dict[str, Any]:
    """Refuse to start while a run lock is held or a task's project is up."""
    holders = layout.run_lock_holders(bench)
    if holders:
        raise BatchError(
            "BATCH_RUN_ACTIVE",
            "A batch orchestration is holding its run lock; restore refused",
            batch_ids=holders,
        )
    projects: list[str] = []
    if task_id is not None:
        projects = layout.running_compose_projects(layout.compose_project_prefix(task_id))
        if projects:
            raise BatchError(
                "COMPOSE_PROJECT_RUNNING",
                "Containers for this task are still running; restore refused",
                projects=projects,
            )
    return {"run_lock_holders": holders, "running_projects": projects}


def _verify_payloads_only(layer: Path, document: dict[str, Any]) -> None:
    checks: list[dict[str, Any]] = []
    _verify_payloads(layer, document, checks)
    failed = [item for item in checks if item["status"] == "FAIL"]
    if failed:
        raise BatchError(
            "PAYLOAD_VERIFICATION_FAILED",
            "Restore refused because the payload archive does not match its manifest",
            failures=failed[:20],
        )


def _install_tree(staged: Path, destination: Path, backup: Path, *, per_method: bool) -> None:
    """Swap a staged tree into place, backing up whatever it replaces."""
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(destination))
        return
    for entry in sorted(staged.iterdir()):
        if per_method and entry.name == "runs" and (destination / "runs").is_dir():
            _install_runs(entry, destination / "runs", backup / "runs")
            continue
        target = destination / entry.name
        layout.move_aside(target, backup / entry.name)
        shutil.move(str(entry), str(target))


def _install_runs(staged: Path, current: Path, backup: Path) -> None:
    """Swap one method at a time: reporting.py cross-checks detect against Update."""
    backup.mkdir(parents=True, exist_ok=True)
    for method in sorted(entry.name for entry in staged.iterdir()):
        target = current / method
        layout.move_aside(target, backup / method)
        shutil.move(str(staged / method), str(target))


def _restore_payloads(
    layer: Path, document: dict[str, Any], bench: Path, backup_root: Path
) -> list[dict[str, Any]]:
    restored = []
    for item in sorted(document["payloads"], key=lambda entry: entry["name"]):
        if item.get("kind") == "docker-save":
            continue
        install_path = item["install_path"]
        with tempfile.TemporaryDirectory(prefix="sdd-checkpoint-restore-") as temporary:
            staged_root = Path(temporary)
            layout.extract_payload(layer, item["name"], staged_root)
            staged = staged_root / install_path
            if not staged.is_dir():
                raise BatchError(
                    "PAYLOAD_LAYOUT_MISMATCH",
                    "Payload does not contain its recorded install path",
                    payload=item["name"],
                    install_path=install_path,
                )
            destination = bench / install_path
            layout.make_writable(destination)
            _install_tree(
                staged,
                destination,
                backup_root / install_path,
                per_method=install_path.startswith("tasks/"),
            )
        restored.append({"payload": item["name"], "install_path": install_path})
    return restored


def _restore_docker_images(layer: Path, document: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for item in document["payloads"]:
        if item.get("kind") != "docker-save":
            continue
        path = layout.payload_path(layer, item["name"])
        result = subprocess.run(
            ["docker", "image", "load", "--input", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            raise BatchError(
                "DOCKER_LOAD_FAILED",
                "Cannot reload the exported images",
                payload=item["name"],
                stderr=result.stderr.decode(errors="replace")[-1500:],
            )
        results.append({"payload": item["name"], "tags": item["tags"]})
    return results


def _restore_tracked(repository_root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tracked inputs are recorded, not packaged: re-check, and only then reset."""
    results = []
    for row in rows:
        path = repository_root / row["path"]
        if path.is_file() and sha256_file(path) == row["sha256"]:
            results.append({"path": row["path"], "status": "UNCHANGED"})
            continue
        if not row["tracked"]:
            raise BatchError(
                "TRACKED_INPUT_UNAVAILABLE",
                "A tracked input was modified and is not packaged; restore it by hand",
                path=row["path"],
                recorded=row["sha256"],
            )
        result = subprocess.run(
            ["git", "-C", str(repository_root), "checkout", "--", row["path"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode or not path.is_file() or sha256_file(path) != row["sha256"]:
            raise BatchError(
                "TRACKED_INPUT_RESET_FAILED",
                "Cannot reset a modified tracked input to its recorded bytes",
                path=row["path"],
                stderr=result.stderr.decode(errors="replace")[-1500:],
            )
        results.append({"path": row["path"], "status": "RESET_FROM_GIT"})
    return results


def restore_shared(
    *, bench: Path, repository_root: Path, yes: bool = False, stamp: str | None = None
) -> dict[str, Any]:
    _assert_required(yes)
    layer = layout.shared_dir(bench)
    path = layout.checkpoint_path(layer)
    if not path.is_file():
        raise BatchError("CHECKPOINT_MISSING", "No shared checkpoint has been captured", path=str(path))
    document = json.loads(path.read_text(encoding="utf-8"))
    _assert_quiescent(bench, task_id=None)
    _verify_payloads_only(layer, document)

    backup_root = layout.backup_paths(bench, stamp or layout.utc_stamp(), "shared")
    payloads = _restore_payloads(layer, document, bench, backup_root)
    images = _restore_docker_images(layer, document)
    tracked = _restore_tracked(repository_root, document["raw_inputs"])
    tracked += _restore_tracked(repository_root, document["deployment_config"])

    verification = verify_shared(bench=bench, repository_root=repository_root)
    return {
        "schema_version": 1,
        "kind": "shared",
        "status": verification["status"],
        "backup_root": str(backup_root),
        "payloads": payloads,
        "images": images,
        "tracked_inputs": tracked,
        "verification": verification,
    }


def restore_pr(
    *,
    bench: Path,
    repository_root: Path,
    task_id: str,
    yes: bool = False,
    stamp: str | None = None,
) -> dict[str, Any]:
    _assert_required(yes)
    layer = layout.pr_dir(bench, task_id)
    path = layout.checkpoint_path(layer)
    if not path.is_file():
        raise BatchError(
            "CHECKPOINT_MISSING", "This task has not been captured", path=str(path), task_id=task_id
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    _assert_quiescent(bench, task_id=task_id)
    _verify_payloads_only(layer, document)

    backup_root = layout.backup_paths(bench, stamp or layout.utc_stamp(), "pr", task_id)
    payloads = _restore_payloads(layer, document, bench, backup_root)

    verification = verify_pr(bench=bench, repository_root=repository_root, task_id=task_id)
    return {
        "schema_version": 1,
        "kind": "pr",
        "task_id": task_id,
        "status": verification["status"],
        "backup_root": str(backup_root),
        "payloads": payloads,
        "verification": verification,
    }
