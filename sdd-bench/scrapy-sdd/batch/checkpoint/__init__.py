"""Templated host-only checkpoints for the Scrapy SDD batch experiments.

The legacy device under ``checkpoints/pre-experiment-pr8073-*`` protects one
hand-built deployment. This package generalises it: one shared layer holds the
irreplaceable deployment-wide state (baseline caches, pinned images, batch
ledgers), and one layer per task holds that task's non-rebuildable evidence.
"""

from __future__ import annotations

from .capture import (
    batch_run_summaries,
    capture_pr,
    capture_pr_all,
    capture_shared,
    covered_targets,
    status,
)
from .layout import (
    backups_dir,
    checkpoint_path,
    pr_dir,
    shared_dir,
)
from .restore import restore_pr, restore_shared
from .verify import verify_pr, verify_shared

__all__ = [
    "backups_dir",
    "batch_run_summaries",
    "capture_pr",
    "capture_pr_all",
    "capture_shared",
    "checkpoint_path",
    "covered_targets",
    "pr_dir",
    "restore_pr",
    "restore_shared",
    "shared_dir",
    "status",
    "verify_pr",
    "verify_shared",
]
