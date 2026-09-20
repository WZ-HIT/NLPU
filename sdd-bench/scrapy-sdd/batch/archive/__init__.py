"""Archive rendered experiment results so they outlive the state they describe.

A batch result card is rebuilt on demand from the batch config, the batch
ledger, and each task manifest. Archiving any of those away does not remove the
card, it degrades it. This package instead writes the rendered page itself --
self-contained, with no external reference to the bench -- so "I can still look
at that experiment" stops depending on the experiment tree surviving.

Nothing in this package loads the results viewer at import time. See
``viewer.py`` for why that matters.
"""

from __future__ import annotations

from .layout import archive_root, manifest_path
from .snapshot import (
    FAILURE_STATES,
    archive_batch,
    archive_cards,
    archive_selected,
    card_content_sha,
    list_snapshots,
    read_manifest,
    record_failure,
    settlement,
    status,
)
from .viewer import ViewerUnavailable

# ``verify`` is deliberately *not* re-exported here. The function and the module
# that holds it would want the same name, and the re-export wins: the package
# attribute becomes the function, so ``from batch.archive.verify import verify``
# silently yields the function instead of the module and
# ``batch.archive.verify.verify`` raises. Import it from its own module.
__all__ = [
    "FAILURE_STATES",
    "ViewerUnavailable",
    "archive_batch",
    "archive_cards",
    "archive_root",
    "archive_selected",
    "card_content_sha",
    "list_snapshots",
    "manifest_path",
    "read_manifest",
    "record_failure",
    "settlement",
    "status",
]
