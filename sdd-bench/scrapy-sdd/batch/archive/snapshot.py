"""Archive rendered experiment results, once, as they reach a conclusion.

The problem this solves is that a batch result card is not self-contained. The
viewer rebuilds a card from three anchors -- the batch config, the batch ledger,
and each task manifest -- so archiving ``tasks/`` away does not remove the card,
it degrades it. A rendered HTML page keeps none of those dependencies.

Two properties shape everything below.

**The identity of a snapshot is a digest of its inputs, never of its bytes.**
``build_html`` stamps the current time into the page footer, so the same
evidence rendered twice produces different files. Content-addressing the HTML is
therefore impossible, and the idempotency key is derived from ``batch_targets``
-- the exact model the renderer consumes -- instead.

**That key deliberately excludes the ledger digest.** A ``--resume`` over an
already-sealed batch appends one ``SKIPPED_RESUME`` event per target. The ledger
bytes change; the meaning does not, and ``batch_targets`` collapses those events
away. Digesting the ledger would turn every idempotent resume into a fresh
snapshot of an unchanged result.

Nothing here is allowed to fail an experiment run. The trigger in
``orchestrator`` catches broadly and reports; see :func:`archive_batch`.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
from pathlib import Path
from typing import Any, Iterable

from ..core import BatchError, canonical_sha256, display_path, sha256_file, write_json
from . import layout, viewer

# The batch ledger's full vocabulary is larger than "finished" and "failed".
# These two are the states that mean an attempt concluded badly: the run is
# over for that target, and re-running it takes an explicit --retry.
FAILURE_STATES = frozenset({"FAILED", "BLOCKED"})

REASON_VALUES = ("auto", "manual", "refresh")


# --------------------------------------------------------------------------
# Manifest access
# --------------------------------------------------------------------------


@contextlib.contextmanager
def manifest_lock(bench: Path):
    """Serialize read-decide-write against the manifest.

    The run-duration lock in ``orchestrator`` is per batch, so two different
    batches can finish at the same moment and archive concurrently. This lock is
    global to the archive, and is always taken *after* any run lock, never
    before.
    """
    path = layout.manifest_lock_path(bench)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def empty_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "archive_type": "SDD_RESULT_ARCHIVE",
        "created_at_utc": None,
        "updated_at_utc": None,
        "viewer_version": None,
        "snapshot_count": 0,
        "snapshots": [],
    }


def read_manifest(bench: Path) -> dict[str, Any]:
    path = layout.manifest_path(bench)
    if not path.is_file():
        return empty_manifest()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchError(
            "ARCHIVE_MANIFEST_UNREADABLE",
            "The archive manifest cannot be read",
            path=str(path),
            reason=str(exc),
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("snapshots"), list):
        raise BatchError(
            "ARCHIVE_MANIFEST_MALFORMED",
            "The archive manifest does not have the expected shape",
            path=str(path),
        )
    return value


def record_failure(bench: Path, batch_id: str, detail: dict[str, Any]) -> None:
    """Append one line to the failure trace, swallowing any error.

    This is called from the failure path, so it must not be able to raise: a
    trace that cannot be written is a smaller problem than an exception thrown
    while handling one. It lives inside the archive directory so a failed
    archive never leaves a stray file under ``batch/runs/``.
    """
    try:
        path = layout.error_log_path(bench)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"recorded_at_utc": layout.utc_now(), "batch_id": batch_id, "error": detail},
            ensure_ascii=False,
            sort_keys=True,
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:  # noqa: BLE001 - a trace failure must never surface
        pass


def _latest_record(snapshots: list[dict[str, Any]], experiment_id: str) -> dict[str, Any] | None:
    for record in reversed(snapshots):
        if record.get("experiment_id") == experiment_id:
            return record
    return None


# --------------------------------------------------------------------------
# The completion predicate and the digest
# --------------------------------------------------------------------------


def _target_key(target: Any) -> str:
    return ":".join(
        [target.task_id, target.method, target.stage, target.run_id, target.mode or "none"]
    )


def settlement(targets: list[Any], terminal_states: Iterable[str]) -> dict[str, Any]:
    """Whether every configured target has reached a conclusion, and which.

    ``overall_status`` in the viewer cannot answer this. It reports ``SEALED`` /
    ``INCOMPLETE`` / ``INVALID``, which has no way to say "this run finished and
    the result was a failure", and its sealed test also requires a resolved
    execution directory -- something a failed target never has. So the decision
    is made directly on ``batch_targets``.

    ``outcome`` is ``SEALED`` only when every target sealed *and* its execution
    resolved, which is the same bar the dashboard uses to render a card as
    sealed.
    """
    terminal = set(terminal_states)
    settled_states = terminal | FAILURE_STATES
    pending = [_target_key(item) for item in targets if item.state not in settled_states]
    failed = [_target_key(item) for item in targets if item.state in FAILURE_STATES]
    if not targets:
        return {"settled": False, "outcome": None, "pending": [], "failed": []}
    if pending:
        return {"settled": False, "outcome": None, "pending": pending, "failed": failed}
    sealed = all(
        item.state in terminal and item.execution is not None for item in targets
    )
    return {
        "settled": True,
        "outcome": "SEALED" if sealed else "FAILED",
        "pending": [],
        "failed": failed,
    }


def target_rows(exp: Any, bench: Path, repository_root: Path) -> list[dict[str, Any]]:
    """The deterministic projection of a card's targets.

    This is both the digest input and the manifest's record of what the snapshot
    covered, so the digest cannot drift from what the manifest claims.
    """
    rows = []
    for item in viewer.module(bench).batch_targets(exp, bench):
        rows.append(
            {
                "task_id": item.task_id,
                "method": item.method,
                "stage": item.stage,
                "run_id": item.run_id,
                "update_mode": item.mode,
                "state": item.state,
                "attempt": item.attempt,
                "execution": (
                    display_path(item.execution, repository_root) if item.execution else None
                ),
                "error": item.error,
            }
        )
    rows.sort(
        key=lambda row: (
            row["task_id"],
            row["method"],
            row["stage"],
            row["run_id"],
            row["update_mode"] or "",
        )
    )
    return rows


def card_content_sha(exp: Any, bench: Path, repository_root: Path, rows: list[dict[str, Any]]) -> str:
    """A stable identity for one card's current evidence.

    Every field is a function of ``batch_targets``, the config, and the viewer
    version. No wall clock, no mtime, no PID -- so re-observing the same state
    reproduces the same digest, and a ``--resume`` that only adds skip events is
    correctly recognised as no change at all.

    ``viewer_version`` is included so an upgraded renderer produces a fresh
    page rather than silently leaving a stale one. The cost is one extra
    snapshot per experiment per version bump, which is the trade we want: the
    archive should say what the tool of the day said.
    """
    loaded = viewer.module(bench)
    config_path = Path(exp.config_path) if exp.config_path else None
    return canonical_sha256(
        {
            "schema_version": 1,
            "experiment_id": exp.experiment_id,
            "batch_id": exp.batch_id,
            "task_id_filter": exp.task_id_filter,
            "viewer_version": loaded.VERSION,
            "config_sha256": (
                sha256_file(config_path) if config_path and config_path.is_file() else None
            ),
            "targets": rows,
        }
    )


# --------------------------------------------------------------------------
# Archiving
# --------------------------------------------------------------------------


def _record(
    *,
    exp: Any,
    bench: Path,
    repository_root: Path,
    rows: list[dict[str, Any]],
    content_sha: str,
    destination: Path,
    reason: str,
    outcome: str,
    supersedes: str | None,
    viewer_version: str,
) -> dict[str, Any]:
    ledger = Path(exp.root) / "ledger.jsonl"
    config_path = Path(exp.config_path) if exp.config_path else None
    return {
        "snapshot_id": destination.stem,
        "experiment_id": exp.experiment_id,
        "batch_id": exp.batch_id,
        "task_id": exp.task_id_filter,
        "scope": "pr" if exp.task_id_filter else "batch",
        "outcome": outcome,
        "reason": reason,
        "content_sha256": content_sha,
        "html_sha256": sha256_file(destination),
        "html_bytes": destination.stat().st_size,
        "viewer_version": viewer_version,
        "archived_at_utc": layout.utc_now(),
        "path": display_path(destination, repository_root),
        "source": {
            "config_path": (
                display_path(config_path, repository_root) if config_path else None
            ),
            "config_sha256": (
                sha256_file(config_path) if config_path and config_path.is_file() else None
            ),
            "ledger_path": display_path(ledger, repository_root) if ledger.is_file() else None,
            "ledger_sha256": sha256_file(ledger) if ledger.is_file() else None,
            "ledger_event_count": _event_count(ledger),
        },
        "targets": rows,
        "supersedes": supersedes,
    }


def _event_count(ledger: Path) -> int | None:
    if not ledger.is_file():
        return None
    return sum(1 for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip())


def _write_snapshot(
    bench: Path,
    exp: Any,
    *,
    stamp: str,
    content_sha: str,
    ordinal: int = 1,
) -> Path:
    """Render one card to a free filename, never overwriting an earlier one."""
    directory = layout.experiment_dir(bench, exp.experiment_id)
    destination = directory / layout.snapshot_name(stamp, content_sha, ordinal)
    while destination.exists():
        ordinal += 1
        destination = directory / layout.snapshot_name(stamp, content_sha, ordinal)
    return viewer.module(bench).write_report(bench, exp, destination)


def archive_cards(
    *,
    bench: Path,
    repository_root: Path,
    cards: list[Any],
    reason: str = "manual",
    refresh: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Archive a set of cards under one manifest transaction.

    Returns a summary whose ``status`` is ``ARCHIVED`` when at least one new
    snapshot was written, ``UNCHANGED`` when every card was already current, and
    ``SKIPPED`` when nothing was eligible. Mixed sets report ``ARCHIVED`` and
    carry the per-card detail alongside.
    """
    if reason not in REASON_VALUES:
        raise BatchError("ARCHIVE_INVALID_REASON", "Unknown archive reason", reason=reason)
    loaded = viewer.module(bench)
    viewer_version = str(loaded.VERSION)
    terminal = set(loaded.TERMINAL_STATES)

    written: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    with manifest_lock(bench):
        document = read_manifest(bench)
        original = list(document["snapshots"])
        snapshots = list(original)

        for exp in cards:
            targets = loaded.batch_targets(exp, bench)
            state = settlement(targets, terminal)
            if not state["settled"] and not force:
                skipped.append(
                    {
                        "experiment_id": exp.experiment_id,
                        "reason": "NOT_SETTLED",
                        "pending": state["pending"][:32],
                    }
                )
                continue
            outcome = state["outcome"] if state["settled"] else "INCOMPLETE"
            rows = target_rows(exp, bench, repository_root)
            content_sha = card_content_sha(exp, bench, repository_root, rows)
            previous = _latest_record(snapshots, exp.experiment_id)

            if (
                previous is not None
                and not refresh
                and previous.get("content_sha256") == content_sha
                and previous.get("viewer_version") == viewer_version
                and (repository_root / previous["path"]).is_file()
            ):
                unchanged.append(
                    {
                        "experiment_id": exp.experiment_id,
                        "snapshot_id": previous["snapshot_id"],
                        "path": previous["path"],
                    }
                )
                continue

            stamp = layout.utc_stamp()
            destination = _write_snapshot(
                bench, exp, stamp=stamp, content_sha=content_sha
            )
            record = _record(
                exp=exp,
                bench=bench,
                repository_root=repository_root,
                rows=rows,
                content_sha=content_sha,
                destination=destination,
                reason="refresh" if (refresh and previous) else reason,
                outcome=outcome,
                supersedes=previous["snapshot_id"] if previous else None,
                viewer_version=viewer_version,
            )
            snapshots.append(record)
            written.append(record)

        if written:
            if snapshots[: len(original)] != original:
                raise BatchError(
                    "ARCHIVE_MANIFEST_TAMPERED",
                    "The archive manifest is append-only, but existing records changed",
                    path=str(layout.manifest_path(bench)),
                )
            document["snapshots"] = snapshots
            document["snapshot_count"] = len(snapshots)
            document["viewer_version"] = viewer_version
            if not document.get("created_at_utc"):
                document["created_at_utc"] = layout.utc_now()
            document["updated_at_utc"] = layout.utc_now()
            write_json(layout.manifest_path(bench), document)

    status = "ARCHIVED" if written else ("UNCHANGED" if unchanged else "SKIPPED")
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "archive_root": display_path(layout.archive_root(bench), repository_root),
        "snapshots": [_snapshot_summary(item, repository_root) for item in written],
        "unchanged": unchanged,
        "skipped": skipped,
    }


def _snapshot_summary(record: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    return {
        "snapshot_id": record["snapshot_id"],
        "experiment_id": record["experiment_id"],
        "scope": record["scope"],
        "outcome": record["outcome"],
        "path": record["path"],
        "html_sha256": record["html_sha256"],
        "html_bytes": record["html_bytes"],
    }


def archive_batch(
    *,
    bench: Path,
    repository_root: Path,
    batch_id: str,
    config_path: Path,
    reason: str = "auto",
    refresh: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Archive every card of one batch, if that batch has concluded.

    The predicate covers the whole config, not the targets a particular run
    happened to select. A filtered run (``--method``, ``--task``) that finishes
    its own slice therefore archives nothing: the batch it belongs to is still
    mid-flight, and a snapshot claiming otherwise would be a lie.
    """
    _assert_repository_root(bench, repository_root)
    loaded = viewer.module(bench)
    overview = viewer.overview_experiment(bench, config_path, batch_id)
    targets = loaded.batch_targets(overview, bench)
    state = settlement(targets, set(loaded.TERMINAL_STATES))

    if not state["settled"] and not force:
        return {
            "schema_version": 1,
            "status": "SKIPPED",
            "reason": "NOT_SETTLED",
            "batch_id": batch_id,
            "outcome": None,
            "pending": state["pending"][:32],
            "pending_count": len(state["pending"]),
            "target_count": len(targets),
        }

    cards = viewer.batch_cards(bench, batch_id)
    if not cards:
        return {
            "schema_version": 1,
            "status": "SKIPPED",
            "reason": "NO_CARDS",
            "batch_id": batch_id,
            "outcome": None,
        }
    result = archive_cards(
        bench=bench,
        repository_root=repository_root,
        cards=cards,
        reason=reason,
        refresh=refresh,
        force=force,
    )
    result["batch_id"] = batch_id
    result["outcome"] = state["outcome"] if state["settled"] else "INCOMPLETE"
    result["target_count"] = len(targets)
    return result


def archive_selected(
    *,
    bench: Path,
    repository_root: Path,
    selectors: list[str] | None = None,
    everything: bool = False,
    force: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """Archive cards chosen by experiment id, for the manual and backfill path.

    A batch's overview id expands to that batch's whole card set, because a
    batch is what a person means when they name one -- and because the per-PR
    cards are separate files that would otherwise be silently lost when the
    overview is archived alone.
    """
    _assert_repository_root(bench, repository_root)
    selectors = list(selectors or [])
    loaded = viewer.module(bench)
    experiments = loaded.discover(bench)
    if everything:
        wanted = [
            item
            for item in experiments
            if item.source_kind == "batch" and item.task_id_filter is None
        ]
        if not wanted:
            raise BatchError("NO_EXPERIMENTS", "No archivable batch experiment was discovered")
        cards = [
            card for item in wanted for card in viewer.batch_cards(bench, item.batch_id)
        ]
    else:
        cards = []
        seen: set[str] = set()
        resolve_error = getattr(loaded, "ViewerError", Exception)
        for selector in selectors:
            try:
                chosen = loaded.resolve(experiments, selector)
            except resolve_error as exc:
                raise BatchError(
                    "EXPERIMENT_NOT_FOUND",
                    "The experiment selector did not resolve to exactly one experiment",
                    selector=selector,
                    reason=str(exc),
                ) from exc
            expansion = (
                viewer.batch_cards(bench, chosen.batch_id)
                if chosen.source_kind == "batch" and chosen.task_id_filter is None
                else [chosen]
            )
            for card in expansion:
                if card.experiment_id in seen:
                    continue
                seen.add(card.experiment_id)
                cards.append(card)

    result = archive_cards(
        bench=bench,
        repository_root=repository_root,
        cards=cards,
        reason="manual",
        refresh=refresh,
        force=force,
    )
    if not everything and result["status"] == "SKIPPED":
        # Naming an experiment is a request to preserve *that* experiment, so a
        # refusal has to be loud: a silent exit-0 with "SKIPPED" inside would let
        # a scheduled backfill report success while nothing was written. `--all`
        # keeps the lenient reading, since an unfinished batch in the middle of a
        # sweep is expected rather than an error.
        raise BatchError(
            "EXPERIMENT_NOT_SEALED",
            "The named experiment has not concluded; use --force to archive it anyway",
            requested=sorted(selectors),
            pending=result["skipped"],
        )
    result["requested"] = sorted(selectors) if not everything else ["<all>"]
    result["card_count"] = len(cards)
    return result


def _assert_repository_root(bench: Path, repository_root: Path) -> None:
    """``batch_targets`` derives the repository root as ``bench.parents[1]``.

    It ignores the argument it is given. That happens to agree with the
    repository layout in every real invocation, but the archive passes a
    repository root down through several layers, so a mismatch is checked
    rather than assumed: reading task manifests out of the wrong tree would
    quietly mis-label every target.
    """
    expected = bench.resolve().parents[1]
    if repository_root.resolve() != expected:
        raise BatchError(
            "ARCHIVE_REPO_ROOT_MISMATCH",
            "The repository root must be the bench's grandparent directory",
            bench=str(bench),
            repository_root=str(repository_root),
            expected=str(expected),
        )


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


def status(bench: Path) -> dict[str, Any]:
    document = read_manifest(bench)
    snapshots = document["snapshots"]
    by_experiment: dict[str, dict[str, Any]] = {}
    for record in snapshots:
        entry = by_experiment.setdefault(
            record["experiment_id"],
            {"experiment_id": record["experiment_id"], "snapshot_count": 0, "latest": None},
        )
        entry["snapshot_count"] += 1
        entry["latest"] = {
            "snapshot_id": record["snapshot_id"],
            "outcome": record["outcome"],
            "archived_at_utc": record["archived_at_utc"],
            "path": record["path"],
        }
    return {
        "archive_root": str(layout.archive_root(bench)),
        "manifest_present": layout.manifest_path(bench).is_file(),
        "viewer_version": document.get("viewer_version"),
        "snapshot_count": len(snapshots),
        "total_html_bytes": sum(int(item.get("html_bytes") or 0) for item in snapshots),
        "experiment_count": len(by_experiment),
        "experiments": [by_experiment[key] for key in sorted(by_experiment)],
    }


def list_snapshots(bench: Path) -> dict[str, Any]:
    document = read_manifest(bench)
    return {
        "archive_root": str(layout.archive_root(bench)),
        "snapshot_count": document["snapshot_count"],
        "snapshots": [
            {
                "snapshot_id": record["snapshot_id"],
                "experiment_id": record["experiment_id"],
                "scope": record["scope"],
                "outcome": record["outcome"],
                "reason": record["reason"],
                "archived_at_utc": record["archived_at_utc"],
                "html_bytes": record["html_bytes"],
                "html_sha256": record["html_sha256"],
                "path": record["path"],
                "supersedes": record["supersedes"],
                "target_count": len(record["targets"]),
            }
            for record in document["snapshots"]
        ],
    }
