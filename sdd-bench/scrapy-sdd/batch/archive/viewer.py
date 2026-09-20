"""The one place that loads ``tools/sdd-results.py``.

That script has a hyphen in its name, so it is not importable as a module. The
repository's established answer is ``importlib.util.spec_from_file_location``,
which ``tests/test_sdd_results.py`` already uses; this module is where that
machinery lives so the rest of the package never sees it.

Two properties matter more than tidiness here.

The load is **lazy and cached**, so importing anything in ``batch.archive`` --
and therefore ``batch.orchestrator`` -- cannot fail because the viewer is
missing or broken. Archiving is a best-effort epilogue to an experiment run;
it must never be able to stop one.

Every failure mode is normalised to a single :class:`ViewerUnavailable`, so the
caller has exactly one thing to catch and the archive records exactly one error
code regardless of whether the file is absent, unparseable, or missing an
attribute it promised.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

VIEWER_FILENAME = "tools/sdd-results.py"
MODULE_NAME = "sdd_archive_viewer"

# The surface the archive actually calls. Checked on load so a viewer that was
# refactored out from under the archive fails loudly at one named place instead
# of with an AttributeError deep inside a render.
REQUIRED_ATTRIBUTES = (
    "Experiment",
    "VERSION",
    "TERMINAL_STATES",
    "ViewerError",
    "batch_targets",
    "discover",
    "resolve",
    "write_report",
)

_CACHE: dict[Path, Any] = {}


class ViewerUnavailable(Exception):
    """The results viewer could not be loaded or does not expose its contract."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": "VIEWER_UNAVAILABLE", "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


def viewer_path(bench: Path) -> Path:
    return bench / VIEWER_FILENAME


def module(bench: Path) -> Any:
    """The loaded viewer module for this bench, loading it at most once."""
    path = viewer_path(bench).resolve()
    cached = _CACHE.get(path)
    if cached is not None:
        return cached
    if not path.is_file():
        raise ViewerUnavailable("The results viewer script is missing", path=str(path))
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ViewerUnavailable(
            "The results viewer script cannot be loaded as a module", path=str(path)
        )
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = loaded
    try:
        spec.loader.exec_module(loaded)
    except Exception as exc:
        raise ViewerUnavailable(
            "The results viewer script failed to execute",
            path=str(path),
            reason=f"{type(exc).__name__}: {exc}",
        ) from exc
    missing = [name for name in REQUIRED_ATTRIBUTES if not hasattr(loaded, name)]
    if missing:
        raise ViewerUnavailable(
            "The results viewer script does not expose the interface the archive needs",
            path=str(path),
            missing=missing,
        )
    _CACHE[path] = loaded
    return loaded


def overview_experiment(bench: Path, config_path: Path, batch_id: str) -> Any:
    """The whole-batch card, built the way discovery builds it.

    Constructed here rather than looked up in ``discover`` for two reasons. The
    trigger has to work before anything is archived, and ``discover`` also walks
    every legacy ``Log/**/experiments`` directory, which is unrelated work. The
    fields below are exactly the ones ``_discover_batches`` sets, so the card
    this produces is the card the dashboard shows.
    """
    loaded = module(bench)
    run_root = bench / "batch" / "runs" / batch_id
    ledger = run_root / "ledger.jsonl"
    modified = ledger.stat().st_mtime if ledger.is_file() else 0.0
    return loaded.Experiment(
        batch_id,
        run_root.resolve(),
        "batch",
        modified,
        source_kind="batch",
        config_path=config_path.resolve(),
        batch_id=batch_id,
    )


def batch_cards(bench: Path, batch_id: str) -> list[Any]:
    """Every card for one batch: the overview first, then one per task.

    Taken from ``discover`` rather than re-expanded here so the archive covers
    exactly the set the dashboard renders, including any future change to how
    cards are named or scoped. A batch whose per-PR cards cannot be discovered
    still yields the overview, so a degraded bench archives less rather than
    nothing.
    """
    loaded = module(bench)
    found = [
        item
        for item in loaded.discover(bench)
        if item.source_kind == "batch" and item.batch_id == batch_id
    ]
    overview = [item for item in found if item.task_id_filter is None]
    per_pr = sorted(
        (item for item in found if item.task_id_filter is not None),
        key=lambda item: item.experiment_id,
    )
    return overview + per_pr
