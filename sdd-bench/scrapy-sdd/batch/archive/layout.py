"""Path, name, and stamp vocabulary for the result archive.

This module decides *where* archived results live and what they are called. It
holds no policy beyond that: whether to archive, what counts as a change, and
how the manifest is maintained all live in ``snapshot.py``.

The archive sits under ``Log/``, which the repository-root ``.gitignore``
excludes. That is deliberate rather than incidental: these snapshots exist to
outlive the experiment state they describe, so they must not be tied to the
tracked tree that will be reorganised underneath them.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ..core import BatchError

ARCHIVE_ROOT = "Log/reports/archive"
MANIFEST_NAME = "manifest.json"
MANIFEST_LOCK_NAME = "manifest.lock"
ERROR_LOG_NAME = "archive-errors.log"
SCHEMA_NAME = "archive-manifest-v1.schema.json"

# An experiment id is either a batch id or "<batch_id>/<task_id>". Both halves
# are already constrained where they are produced, but they are joined onto a
# path here, so they are re-checked rather than trusted.
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _segments(experiment_id: str) -> list[str]:
    parts = experiment_id.split("/")
    if not parts or any(not SAFE_SEGMENT.fullmatch(part) for part in parts):
        raise BatchError(
            "ARCHIVE_UNSAFE_EXPERIMENT_ID",
            "An experiment id may only contain safe path segments",
            experiment_id=experiment_id,
        )
    return parts


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def archive_root(bench: Path) -> Path:
    return bench / ARCHIVE_ROOT


def manifest_path(bench: Path) -> Path:
    return archive_root(bench) / MANIFEST_NAME


def manifest_lock_path(bench: Path) -> Path:
    return archive_root(bench) / MANIFEST_LOCK_NAME


def error_log_path(bench: Path) -> Path:
    return archive_root(bench) / ERROR_LOG_NAME


def schema_path(bench: Path) -> Path:
    return bench / "schemas" / SCHEMA_NAME


def experiment_dir(bench: Path, experiment_id: str) -> Path:
    """The directory holding one experiment's snapshots.

    A per-PR card's id is ``"<batch_id>/<task_id>"``; the separator becomes a
    directory level so the tree reads the way the dashboard does.
    """
    root = archive_root(bench)
    target = root.joinpath(*_segments(experiment_id))
    try:
        target.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        raise BatchError(
            "ARCHIVE_UNSAFE_EXPERIMENT_ID",
            "An experiment id must stay inside the archive root",
            experiment_id=experiment_id,
        ) from None
    return target


def snapshot_name(stamp: str, content_sha256: str, ordinal: int = 1) -> str:
    """A snapshot filename: when it was taken, and what it is a snapshot of.

    The content digest is what keeps this write-once. Identical inputs produce
    an identical stem, so a re-run is recognised as ``UNCHANGED`` before it
    reaches the filesystem; changed inputs produce a different stem, so a new
    result can never land on top of the record of an older one. The timestamp is
    there for the human reading the directory listing.

    The stamp only resolves to the second, so ``ordinal`` disambiguates the
    forced re-renders that ``--refresh`` produces.
    """
    suffix = f"-{ordinal}" if ordinal > 1 else ""
    return f"{stamp}--{content_sha256[:16]}{suffix}.html"
