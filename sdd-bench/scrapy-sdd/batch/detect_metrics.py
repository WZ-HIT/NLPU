"""File-level Detect hit-rate metrics, computed against the host-only gold store.

The question this answers is narrow on purpose: of the test *files* an SDD Agent
reported during Detect, how many are files the pull request actually changed?
That ratio is ``a / b`` -- ``a`` matched, ``b`` reported -- and it is a
precision. Recall (``a / |gold|``) is reported next to it for the reason
``batch/evaluator.py`` already pairs the two: precision alone rewards an Agent
that reports almost nothing, and on this bench that is not hypothetical. Spec
Kit scores 2/2 on PR 8073 by naming two files where the truth is three.

Nothing here is new arithmetic. ``score_ranked`` is the same scorer the Prompt 10
evaluation uses, and the candidate normalisation below is the same loop as
``_target_sets_and_metrics``. What is new is only the *access path*. The
evaluation flow will not look at gold until an approved plan and a sealed batch
exist, which is far more ceremony than "how many did it get right" needs. This
module reads the ledger, the execution directory each target already has, and
the gold store, and stops there.

Three things it deliberately does not do.

It does not touch the experiment: no ledger append, no Docker, no Agent. It is
read-only over the bench and writes exactly one file, under ``Log/``.

It does not fall back to symbol-level matching. A symbol name is not stable --
``TestHttp.test_timeout_x`` in one file and ``TestHttpBase.test_timeout_x`` in
another collide on the bare leaf name, which is exactly the false positive that
made a hand-measured first pass of this bench read 13/13 where the truth was
3/13.

It does not drop a target it cannot score. A failed Detect target is reported as
an error row, never filtered out: a metric computed over the survivors of a
filter is a metric that improves when things break.

The one exception is a target the *provider* cut off before it reported
anything. That run returned no candidate, so it is scored as the zero it is --
with the cause kept in ``warnings`` and ``detail`` -- instead of being reported
as an error that leaves the rates flattering the batch. The direction matters:
zeroing can only lower a rate, never raise it, which is the opposite of the
filter this module refuses to apply, and the allowlist below is short enough
that a genuine failure is never quietly converted into a zero.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from jsonschema import Draft202012Validator

from .archive.viewer import module
from .core import BatchError, canonical_sha256, display_path, write_json
from .evaluator import TEST_PREFIXES, EvaluationError, _safe_path, score_ranked
from .result_view import build as build_result_view

SCHEMA_VERSION = 2
DOCUMENT_TYPE = "DETECT_HIT_RATE"
ROLLUP_DOCUMENT_TYPE = "DETECT_HIT_RATE_ROLLUP"
METRIC_DEFINITION_VERSION = "detect-metrics-v2"
GRANULARITY = "file"
DETECTION_MANIFEST_TYPE = "SEALED_DETECTION"
GOLD_STORE_TYPE = "HOST_ONLY_GOLD"
GOLD_STORE_RELATIVE = PurePosixPath("batch") / "gold"
REPORTS_RELATIVE = PurePosixPath("Log") / "reports" / "detect-metrics"
SCHEMA_RELATIVE = PurePosixPath("schemas") / "detect-metrics-v2.schema.json"
# Rollups live in a subdirectory rather than beside the batch reports: `status`
# globs the top level for batch reports, and a rollup is not one -- it names no
# batch, consumes no ledger, and answering "which batches have been scored" with
# a document that was scored from two of them would be a lie of omission.
ROLLUPS_RELATIVE = REPORTS_RELATIVE / "rollups"
ROLLUP_SCHEMA_RELATIVE = PurePosixPath("schemas") / "detect-metrics-rollup-v2.schema.json"
# Fixed, and always all three, so a reader comparing methods never has to ask
# whether a missing row means "no targets" or "the table dropped a column".
METHOD_ORDER = ("openspec", "speckit", "cc-sdd")
BATCH_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
# The Agent session of a Detect run can be cut off by the model provider rather
# than by anything in the task: the session ends with `turn.failed` and this
# message, and no artifact is ever harvested. The string is the provider's, so
# this is an allowlist of one -- a failure that is not on it stays an ERROR row.
UPSTREAM_ABORT_SIGNATURES = ("shared rollout token budget exhausted",)
UPSTREAM_ABORT_WARNING = "no_candidate_upstream_quota_abort"

DEFINITIONS = {
    "hit_rate": "|detected_files ∩ gold_files| / |detected_files|",
    "recall": "|detected_files ∩ gold_files| / |gold_files|",
    "a": "detected files that the pull request actually changed",
    "b": "detected files",
    "granularity": "one test case is one test file path; symbols are not compared",
}


def reports_root(bench: Path) -> Path:
    return bench.joinpath(*REPORTS_RELATIVE.parts)


def document_path(bench: Path, batch_id: str) -> Path:
    return reports_root(bench) / f"{batch_id}.json"


def _validate_batch_id(batch_id: str) -> None:
    if not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id):
        raise BatchError(
            "INVALID_BATCH_ID",
            "batch id must be lowercase letters, digits, dot, underscore or hyphen",
            batch_id=batch_id,
        )


def _schema_validate(document: dict[str, Any], schema: Path) -> None:
    validator = Draft202012Validator(json.loads(schema.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise BatchError(
            "SCHEMA_VALIDATION_FAILED",
            "Generated artifact failed schema validation",
            schema=str(schema),
            errors=[error.message for error in errors],
        )


def _batch_experiment(loaded: Any, bench: Path, batch_id: str) -> Any:
    """The whole-batch card for ``batch_id``, taken from the viewer's own discovery.

    Discovered rather than constructed so the set of targets measured here is the
    set the dashboard renders. The per-PR cards are excluded deliberately: they
    carry a ``task_id_filter`` and would narrow the walk to one task.
    """
    for item in loaded.discover(bench):
        if item.source_kind == "batch" and item.batch_id == batch_id and item.task_id_filter is None:
            return item
    raise BatchError(
        "BATCH_NOT_FOUND",
        "No batch with a config and a ledger was discovered under this bench",
        batch_id=batch_id,
    )


def _gold_sources(bench: Path, task_id: str) -> tuple[list[str] | None, str | None, str | None, str | None]:
    """Return ``(gold_files, gold_sha256, error_code, detail)`` for one task.

    Absent gold is ``(None, None, None, None)`` and is not an error: a task that
    was never audited simply has no reference to score against, and the row says
    ``N/A``. A gold store that exists and cannot be trusted is an error, because
    silently treating it as absent would report ``N/A`` for a broken file.
    """
    path = bench.joinpath(*GOLD_STORE_RELATIVE.parts) / task_id / "gold-store.json"
    if path.is_symlink() or not path.is_file():
        return None, None, None, None
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, None, "GOLD_STORE_INVALID", f"gold store cannot be read: {type(exc).__name__}"
    if not isinstance(document, dict):
        return None, None, "GOLD_STORE_INVALID", "gold store is not a JSON object"
    if document.get("store_type") != GOLD_STORE_TYPE:
        return None, None, "GOLD_STORE_INVALID", f"gold store type is {document.get('store_type')!r}"
    supplied = document.get("gold_target_files")
    if not isinstance(supplied, list):
        return None, None, "GOLD_STORE_INVALID", "gold_target_files is not an array"
    files: list[str] = []
    for value in supplied:
        try:
            # tests_only is deliberately False on the gold side. The asymmetry is
            # the point: candidates are checked strictly because an Agent may name
            # anything, while gold is the authority and is a test file by
            # construction. Applying the candidate rule here would silently delete
            # gold the Agent could never have matched anyway -- see the
            # gold_outside_test_roots warning, which says so out loud instead.
            files.append(_safe_path(value))
        except EvaluationError:
            return None, None, "GOLD_STORE_INVALID", "gold store names a path that is not repository-relative"
    digest = hashlib.sha256(raw).hexdigest()
    return sorted(set(files)), digest, None, None


def _candidate_files(candidates: list[Any]) -> tuple[list[str], list[str]]:
    """Normalise Detect candidates to file paths, keeping their reported order.

    The order is meaningful -- ``score_ranked`` reads it as the Agent's own
    ranking for ``hit_at_k`` -- so it is preserved, not sorted. Rejected entries
    are counted, never raised: a bad path is a fact about the run, not a reason
    to refuse to measure it. They are also why ``invalid_count`` is reported at
    every level: dropping a path shrinks ``b`` and therefore *raises* the hit
    rate, so it has to be visible.
    """
    predicted: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        value = item.get("path") if isinstance(item, dict) else None
        try:
            path = _safe_path(value, tests_only=True)
        except EvaluationError:
            invalid.append("invalid-path")
            continue
        if path in seen:
            invalid.append(f"{path}:duplicate")
            continue
        seen.add(path)
        predicted.append(path)
    return predicted, invalid


def _upstream_abort(bench: Path, target: Any) -> str | None:
    """The model provider's abort message for a target, or ``None``.

    Reads only the Agent session that the ledger's current attempt already
    names -- the one artifact a cut-off run does leave behind, since the ledger
    stores ``details_sha256`` and drops the text. The last terminating event
    wins: a session that tripped the limit twice ends on the one that ended it.
    """
    if target.state != "FAILED" or target.attempt is None:
        return None
    execution = (
        bench / "tasks" / target.task_id / "runs" / target.method
        / "detect" / "executions" / target.run_id / f"attempt-{target.attempt}"
    )
    try:
        # The identifiers come from the batch config, but nothing here joins one
        # onto a path without checking where it lands.
        execution.resolve().relative_to(bench.resolve())
    except (OSError, ValueError):
        return None
    session = execution / "agent.jsonl"
    if session.is_symlink() or not session.is_file():
        return None
    try:
        raw = session.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    message = None
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") not in ("turn.failed", "error"):
            continue
        candidate = event.get("message")
        if not isinstance(candidate, str):
            nested = event.get("error")
            candidate = nested.get("message") if isinstance(nested, dict) else None
        if isinstance(candidate, str):
            message = candidate
    if message is None or not any(signature in message for signature in UPSTREAM_ABORT_SIGNATURES):
        return None
    return message


def upstream_aborted(row: dict[str, Any]) -> bool:
    """Whether a row is a zero because the provider cut the run, not because the method found nothing.

    The warning is the machine-readable half of the abort -- ``detail`` carries
    the provider's own words -- so a rendering can tell "no answer was recorded"
    apart from "the answer was that there is nothing" without parsing prose.
    """
    return UPSTREAM_ABORT_WARNING in row["warnings"]


def _row(bench: Path, target: Any, indexed: dict[str, Any], gold: tuple[Any, ...]) -> dict[str, Any]:
    gold_files, gold_sha, gold_code, gold_detail = gold
    row: dict[str, Any] = {
        "target_key": indexed["target_key"],
        "target_id": indexed["target_id"],
        "ledger_event": indexed["ledger_event"],
        "seal": indexed["seal"],
        "task_id": target.task_id,
        "method": target.method,
        "run_id": target.run_id,
        "state": target.state,
        "attempt": target.attempt,
        "status": "OK",
        "error_code": None,
        "detail": None,
        "gold_available": gold_files is not None,
        "scorable": False,
        "gold_store_sha256": gold_sha,
        "detection_manifest_sha256": None,
        "predicted_files": [],
        "gold_files": [],
        "matched_files": [],
        "missing_gold_files": [],
        "extra_files": [],
        "invalid_files": [],
        "warnings": [],
        "metrics": None,
    }

    def fail(code: str, detail: str) -> dict[str, Any]:
        row["status"] = "ERROR"
        row["error_code"] = code
        row["detail"] = detail
        return row

    if target.execution is None:
        abort = _upstream_abort(bench, target)
        if abort is not None:
            # Scored rather than errored: the run reported no candidate, which
            # every rate reads as a miss. `detail` carries why, `warnings` makes
            # it countable without parsing prose, and `state` still says FAILED.
            row["warnings"].append(UPSTREAM_ABORT_WARNING)
            row["detail"] = (
                "Agent session was aborted by the model provider before it "
                f"reported a candidate; scored as no finding ({abort})"
            )
            if gold_files is None:
                row["status"] = "NO_GOLD"
                return row
            row["gold_files"] = gold_files
            row["missing_gold_files"] = gold_files
            if any(PurePosixPath(value).parts[0] not in TEST_PREFIXES for value in gold_files):
                row["warnings"].append("gold_outside_test_roots")
            row["scorable"] = True
            row["metrics"] = score_ranked(
                [], gold_files, invalid_count=0, missing_count=len(gold_files)
            )
            return row
        return fail("DETECT_TARGET_UNAVAILABLE", target.error or "no sealed execution")
    # The execution directory, not update/sealed-input. The two agree today (all
    # nine pairs hash equal), but sealed-input is the copy a re-run displaces and
    # this one is what the ledger's current attempt names -- and batch_targets has
    # already checked that the directory is not a symlink and that its summary
    # agrees on task, method and SEALED status.
    manifest_path = target.execution / "detection-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return fail("DETECT_MANIFEST_MISSING", "terminal execution has no detection manifest")
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return fail("DETECT_MANIFEST_MISSING", f"detection manifest cannot be read: {type(exc).__name__}")
    if not isinstance(manifest, dict):
        return fail("DETECT_MANIFEST_MISSING", "detection manifest is not a JSON object")
    row["detection_manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    if (
        manifest.get("manifest_type") != DETECTION_MANIFEST_TYPE
        or manifest.get("task_id") != target.task_id
        or manifest.get("method") != target.method
    ):
        return fail("DETECT_MANIFEST_IDENTITY_MISMATCH", "detection manifest does not name this target")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        return fail("DETECT_MANIFEST_INVALID", "candidates is not an array")

    predicted, invalid = _candidate_files(candidates)
    row["predicted_files"] = predicted
    row["invalid_files"] = invalid
    if invalid:
        # Rejecting a path shrinks b, and a smaller b is a *higher* hit rate. The
        # row is still scoreable and still says OK; this is the flag that says the
        # rate came from a run that reported something unusable.
        row["warnings"].append("invalid_candidate_paths_rejected")

    if gold_code is not None:
        return fail(gold_code, gold_detail or "gold store is unusable")
    if gold_files is None:
        row["status"] = "NO_GOLD"
        return row

    row["gold_files"] = gold_files
    predicted_set = set(predicted)
    gold_set = set(gold_files)
    if any(PurePosixPath(value).parts[0] not in TEST_PREFIXES for value in gold_files):
        # A gold file outside the test roots can never be matched: the candidate
        # side rejects it before scoring. Leaving that unsaid would cap recall
        # below 1.0 for a reason that looks like the detector's fault.
        row["warnings"].append("gold_outside_test_roots")
    row["matched_files"] = sorted(predicted_set & gold_set)
    row["extra_files"] = sorted(predicted_set - gold_set)
    row["missing_gold_files"] = sorted(gold_set - predicted_set)
    row["scorable"] = True
    row["metrics"] = score_ranked(
        predicted,
        gold_files,
        invalid_count=len(invalid),
        missing_count=len(gold_set - predicted_set),
    )
    return row


def _ratio(numerator: int, denominator: int) -> float | None:
    """``None`` when the ratio is undefined, never 0.

    A method that reported nothing has no precision; scoring that as zero would
    read as "got everything wrong" and scoring it as one would read as "perfect".
    """
    return numerator / denominator if denominator else None


def _method_summary(method: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    scorable = [row for row in rows if row["scorable"]]
    tp = sum(row["metrics"]["tp"] for row in scorable)
    fp = sum(row["metrics"]["fp"] for row in scorable)
    fn = sum(row["metrics"]["fn"] for row in scorable)
    precisions = [row["metrics"]["precision"] for row in scorable]
    recalls = [row["metrics"]["recall"] for row in scorable]
    f1s = [row["metrics"]["f1"] for row in scorable]
    hit_rate_micro = _ratio(tp, tp + fp)
    recall_micro = _ratio(tp, tp + fn)
    f1_micro = (
        2 * hit_rate_micro * recall_micro / (hit_rate_micro + recall_micro)
        if hit_rate_micro is not None and recall_micro is not None and hit_rate_micro + recall_micro
        else None
    )
    return {
        "method": method,
        "row_count": len(rows),
        "scorable_count": len(scorable),
        "error_count": sum(row["status"] == "ERROR" for row in rows),
        "no_gold_count": sum(row["status"] == "NO_GOLD" for row in rows),
        "a": tp,
        "b": tp + fp,
        "gold_count": tp + fn,
        "hit_rate_micro": hit_rate_micro,
        "recall_micro": recall_micro,
        "f1_micro": f1_micro,
        "hit_rate_macro": sum(precisions) / len(precisions) if precisions else None,
        "recall_macro": sum(recalls) / len(recalls) if recalls else None,
        "f1_macro": sum(f1s) / len(f1s) if f1s else None,
    }


def compute(bench: Path, batch_id: str) -> dict[str, Any]:
    """Build the hit-rate document for one batch. Pure: reads, never writes.

    Deterministic by construction -- every field is a function of the batch
    config, the ledger, the sealed manifests and the gold stores. There is no
    timestamp, because there is no reason for one: the document that answers the
    same question twice is the same document, and that is testable.
    """
    _validate_batch_id(batch_id)
    loaded = module(bench)
    experiment = _batch_experiment(loaded, bench, batch_id)
    result_view = build_result_view(experiment.config_path, bench, bench.parents[1])
    targets = [item for item in loaded.batch_targets(experiment, bench) if item.stage == "detect"]
    targets.sort(
        key=lambda item: (
            item.task_id,
            METHOD_ORDER.index(item.method) if item.method in METHOD_ORDER else len(METHOD_ORDER),
        )
    )

    gold_cache: dict[str, tuple[Any, ...]] = {}
    rows: list[dict[str, Any]] = []
    for target in targets:
        if target.task_id not in gold_cache:
            gold_cache[target.task_id] = _gold_sources(bench, target.task_id)
        key = loaded._target_key(target.task_id, target.method, target.stage, target.run_id, target.mode)
        indexed = result_view["targets"][key]
        rows.append(_row(bench, target, indexed, gold_cache[target.task_id]))

    methods = [
        _method_summary(method, [row for row in rows if row["method"] == method])
        for method in METHOD_ORDER
    ]
    error_count = sum(row["status"] == "ERROR" for row in rows)
    no_gold_count = sum(row["status"] == "NO_GOLD" for row in rows)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "document_type": DOCUMENT_TYPE,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "granularity": GRANULARITY,
        "batch_id": batch_id,
        "result_view_sha256": result_view["view_sha256"],
        "status": "EMPTY" if not rows else ("PARTIAL" if error_count or no_gold_count else "OK"),
        "definitions": DEFINITIONS,
        "counts": {
            "target_count": len(rows),
            "ok_count": sum(row["status"] == "OK" for row in rows),
            "error_count": error_count,
            "no_gold_count": no_gold_count,
            "scorable_count": sum(row["scorable"] for row in rows),
            "invalid_candidate_count": sum(len(row["invalid_files"]) for row in rows),
            "warning_count": sum(len(row["warnings"]) for row in rows),
        },
        "rows": rows,
        "methods": methods,
    }
    document["metric_set_sha256"] = canonical_sha256(document)
    return document


def check(bench: Path, batch_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Compute, validate, and (unless dry) overwrite the batch's report file."""
    document = compute(bench, batch_id)
    _schema_validate(document, bench.joinpath(*SCHEMA_RELATIVE.parts))
    path = document_path(bench, batch_id)
    changed = True
    if not dry_run:
        root = reports_root(bench)
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        try:
            changed = path.read_text(encoding="utf-8") != json.dumps(
                document, ensure_ascii=False, indent=2
            ) + "\n"
        except (OSError, UnicodeError):
            changed = True
        # No refuse_overwrite: this file is a derived view, and a second run that
        # produces different numbers is the interesting case, not a mistake.
        write_json(path, document)
        # The document names gold files. Log/ is gitignored, but the mode is set
        # anyway: the prompt10 gold store is 0o600 for the same reason.
        path.chmod(0o600)
    return {
        "batch_id": batch_id,
        "status": document["status"],
        "counts": document["counts"],
        "methods": document["methods"],
        "metric_set_sha256": document["metric_set_sha256"],
        "path": display_path(path, bench.parents[1]),
        "written": not dry_run,
        "changed": changed,
    }


def show(bench: Path, batch_id: str) -> dict[str, Any]:
    """Read back the recorded document. Never recomputes.

    A reader asking what the numbers were must not be handed what they would be
    now: the bench moves, and a silently recomputed answer to a historical
    question is worse than no answer.
    """
    _validate_batch_id(batch_id)
    path = document_path(bench, batch_id)
    if path.is_symlink() or not path.is_file():
        raise BatchError(
            "DETECT_METRICS_NOT_FOUND",
            "No recorded hit-rate document for this batch; run check first",
            batch_id=batch_id,
            path=display_path(path, bench.parents[1]),
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchError(
            "DETECT_METRICS_NOT_FOUND",
            "Recorded hit-rate document cannot be read",
            batch_id=batch_id,
            reason=f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(document, dict) or document.get("metric_definition_version") != METRIC_DEFINITION_VERSION:
        raise BatchError(
            "DETECT_METRICS_NOT_FOUND",
            "Recorded document is not a hit-rate document of this version",
            batch_id=batch_id,
        )
    _schema_validate(document, bench.joinpath(*SCHEMA_RELATIVE.parts))
    return document


def status(bench: Path) -> dict[str, Any]:
    """List what has been recorded, read-only, without recomputing any of it."""
    root = reports_root(bench)
    records: list[dict[str, Any]] = []
    if root.is_dir() and not root.is_symlink():
        for path in sorted(root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                stat = path.stat()
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                records.append({"batch_id": path.stem, "status": "UNREADABLE"})
                continue
            counts = document.get("counts") if isinstance(document, dict) else None
            records.append(
                {
                    "batch_id": path.stem,
                    "path": display_path(path, bench.parents[1]),
                    "status": document.get("status") if isinstance(document, dict) else None,
                    "metric_set_sha256": document.get("metric_set_sha256") if isinstance(document, dict) else None,
                    "row_count": counts.get("target_count") if isinstance(counts, dict) else None,
                    "error_count": counts.get("error_count") if isinstance(counts, dict) else None,
                    "size_bytes": stat.st_size,
                    "written_at_utc": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                }
            )
    return {
        "reports_root": display_path(root, bench.parents[1]),
        "report_count": len(records),
        "reports": records,
    }


# -- cross-batch rollup ------------------------------------------------------
#
# One table over several batches, for the case the batch cannot cover by itself.
# A Detect seal is a single slot per task and method -- Update consumes it -- so a
# task that has sealed once cannot be re-detected into a new batch. Widening an
# experiment therefore means unioning the batches that exist, and the union has to
# be arithmetic over the rows rather than an average of the already-summarised
# methods: micro rates do not commute with averaging.


def rollups_root(bench: Path) -> Path:
    return bench.joinpath(*ROLLUPS_RELATIVE.parts)


def rollup_path(bench: Path, rollup_id: str) -> Path:
    return rollups_root(bench) / f"{rollup_id}.json"


def rollup_markdown_path(bench: Path, rollup_id: str) -> Path:
    return rollups_root(bench) / f"{rollup_id}.md"


def _validate_rollup_id(value: str) -> None:
    if not isinstance(value, str) or not BATCH_ID_RE.fullmatch(value):
        raise BatchError(
            "INVALID_ROLLUP_ID",
            "rollup id must be lowercase letters, digits, dot, underscore or hyphen",
            rollup_id=value,
        )


def _source_document(bench: Path, batch_id: str) -> dict[str, Any]:
    """One recorded batch document, refused if it no longer describes this bench.

    ``show`` reads back what was recorded and never recomputes, which is right for
    a historical question and wrong for this one: a rollup adds the two documents
    together, so a source that the bench would no longer produce would make the
    total a statement about two different benches. Recomputing and comparing
    ``metric_set_sha256`` is the whole guard, and it costs one read of the ledger
    and the gold per source.
    """
    document = show(bench, batch_id)
    recomputed = compute(bench, batch_id)
    if recomputed["metric_set_sha256"] != document["metric_set_sha256"]:
        raise BatchError(
            "ROLLUP_SOURCE_STALE",
            "A recorded batch report no longer matches what this bench computes; re-run check",
            batch_id=batch_id,
            recorded=document["metric_set_sha256"],
            recomputed=recomputed["metric_set_sha256"],
        )
    return document


def rollup(
    bench: Path, batch_ids: Sequence[str], rollup_id: str, *, dry_run: bool = False
) -> dict[str, Any]:
    """Union recorded batch reports into one document, and render it as Markdown.

    Refuses rather than reconciles. A task and method appearing in two sources is
    an error, not a duplicate to collapse: the same target scored twice means one
    of the two batches is not the evidence it claims to be, and silently keeping
    either copy would hide that.
    """
    _validate_rollup_id(rollup_id)
    if len(batch_ids) < 2 or len(set(batch_ids)) != len(batch_ids):
        raise BatchError(
            "ROLLUP_SOURCE_INVALID",
            "A rollup needs at least two distinct batches, and a batch may appear once",
            batch_ids=list(batch_ids),
        )
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    origin: dict[tuple[str, str], str] = {}
    for batch_id in batch_ids:
        document = _source_document(bench, batch_id)
        for row in document["rows"]:
            key = (row["task_id"], row["method"])
            if key in origin:
                raise BatchError(
                    "ROLLUP_DUPLICATE_TARGET",
                    "The same task and method appear in two source batches",
                    task_id=key[0],
                    method=key[1],
                    batches=[origin[key], batch_id],
                )
            origin[key] = batch_id
            rows.append(row)
        sources.append({
            "batch_id": batch_id,
            "status": document["status"],
            "path": display_path(document_path(bench, batch_id), bench.parents[1]),
            "row_count": len(document["rows"]),
            "metric_set_sha256": document["metric_set_sha256"],
        })
    # The same order `compute` uses, so a reader comparing a rollup with its
    # sources reads the same task in the same place in both.
    rows.sort(
        key=lambda item: (
            item["task_id"],
            METHOD_ORDER.index(item["method"]) if item["method"] in METHOD_ORDER else len(METHOD_ORDER),
        )
    )
    methods = [
        _method_summary(method, [row for row in rows if row["method"] == method])
        for method in METHOD_ORDER
    ]
    error_count = sum(row["status"] == "ERROR" for row in rows)
    no_gold_count = sum(row["status"] == "NO_GOLD" for row in rows)
    document = {
        "schema_version": SCHEMA_VERSION,
        "document_type": ROLLUP_DOCUMENT_TYPE,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "granularity": GRANULARITY,
        "rollup_id": rollup_id,
        "status": "EMPTY" if not rows else ("PARTIAL" if error_count or no_gold_count else "OK"),
        "definitions": DEFINITIONS,
        "sources": sources,
        "counts": {
            "target_count": len(rows),
            "ok_count": sum(row["status"] == "OK" for row in rows),
            "error_count": error_count,
            "no_gold_count": no_gold_count,
            "scorable_count": sum(row["scorable"] for row in rows),
            "invalid_candidate_count": sum(len(row["invalid_files"]) for row in rows),
            "warning_count": sum(len(row["warnings"]) for row in rows),
        },
        "rows": rows,
        "methods": methods,
    }
    document["metric_set_sha256"] = canonical_sha256(document)
    _schema_validate(document, bench.joinpath(*ROLLUP_SCHEMA_RELATIVE.parts))
    markdown = rollup_markdown(document)
    json_path = rollup_path(bench, rollup_id)
    md_path = rollup_markdown_path(bench, rollup_id)
    if not dry_run:
        root = rollups_root(bench)
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        # Like the batch report, this is a derived view: a second run that
        # produces different numbers is the interesting case, not a mistake.
        write_json(json_path, document)
        json_path.chmod(0o600)
        md_path.write_text(markdown, encoding="utf-8")
        md_path.chmod(0o600)
    return {
        "rollup_id": rollup_id,
        "status": document["status"],
        "counts": document["counts"],
        "methods": document["methods"],
        "sources": sources,
        "metric_set_sha256": document["metric_set_sha256"],
        "path": display_path(json_path, bench.parents[1]),
        "markdown_path": display_path(md_path, bench.parents[1]),
        "markdown": markdown,
        "written": not dry_run,
    }


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def rollup_markdown(document: dict[str, Any]) -> str:
    """Render a rollup document as the two tables it is read as.

    The per-method block is the headline, the per-task matrix is the evidence
    behind it, and every cell is written as ``a/b`` -- matched over reported --
    so a reader re-derives the rate instead of trusting a decimal. The caveats
    are part of the rendering rather than a footnote in a paper: a target that
    reported a single file is 0% or 100% and says nothing about discrimination,
    and on this bench that is most of them. A target the provider aborted is
    scored as a miss, and its cell is indistinguishable from a method that
    reported nothing -- so the caveats name those rows instead of leaving the
    reader to guess which zeroes are performance and which are availability.
    """
    task_ids = sorted({row["task_id"] for row in document["rows"]})
    lines = [
        f"# Detect hit rate rollup: {document['rollup_id']}",
        "",
        f"{document['counts']['target_count']} targets over {len(task_ids)} tasks, "
        f"union of {len(document['sources'])} batch reports.",
        "",
        "Sources:",
        "",
    ]
    for source in document["sources"]:
        lines.append(
            f"- {source['batch_id']} -- {source['row_count']} targets, "
            f"{source['status']}, metric set `{source['metric_set_sha256']}`"
        )
    lines += [
        "",
        "## Per method",
        "",
        "| method | targets | scorable | a | b | gold | hit rate (micro) | recall (micro) | F1 (micro) | hit rate (macro) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for method in document["methods"]:
        lines.append(
            "| {method} | {row_count} | {scorable_count} | {a} | {b} | {gold_count} | "
            "{micro} | {recall} | {f1} | {macro} |".format(
                micro=_rate(method["hit_rate_micro"]),
                recall=_rate(method["recall_micro"]),
                f1=_rate(method["f1_micro"]),
                macro=_rate(method["hit_rate_macro"]),
                **method,
            )
        )
    lines += [
        "",
        "## Per task",
        "",
        "Cells are `matched/reported`; `error` and `no_gold` rows carry no rate.",
        "",
        "| task | gold | " + " | ".join(METHOD_ORDER) + " |",
        "| --- | --- | " + " | ".join("---" for _ in METHOD_ORDER) + " |",
    ]
    for task_id in task_ids:
        gold = "n/a"
        cells = []
        for method in METHOD_ORDER:
            row = next(
                (item for item in document["rows"]
                 if item["task_id"] == task_id and item["method"] == method),
                None,
            )
            if row is None:
                cells.append("-")
            elif row["status"] != "OK":
                cells.append(row["status"].lower())
            else:
                gold = str(len(row["gold_files"]))
                cells.append(f"{row['metrics']['tp']}/{row['metrics']['tp'] + row['metrics']['fp']}")
        lines.append(f"| {task_id} | {gold} | " + " | ".join(cells) + " |")
    # Scored rows only: a row with no gold is already named under the errors
    # below, and it has no rate for an abort to have pulled down.
    aborted = [
        row for row in document["rows"]
        if row["status"] == "OK" and upstream_aborted(row)
    ]
    single = [
        row for row in document["rows"]
        if row["status"] == "OK" and not upstream_aborted(row)
        and row["metrics"]["tp"] + row["metrics"]["fp"] <= 1
    ]
    lines += [
        "",
        "## Caveats",
        "",
        f"- {len(single)} of {len(document['rows'])} targets reported at most one file. "
        "Those rows score 0.000 or 1.000 and carry no information about discrimination; "
        "a macro average over them moves when a method reports one file instead of two.",
    ]
    if aborted:
        lines.append(
            f"- {len(aborted)} targets were aborted by the model provider before the agent "
            f"produced a draft (`{UPSTREAM_ABORT_WARNING}`). They are scored as the misses they "
            "are -- 0 matched over 0 reported -- so their `0/0` cells mean no answer was "
            "recorded, not that the method reported nothing. They still pull the rate down, "
            "which is the point of scoring an abort as a miss rather than dropping the row:"
        )
        for row in aborted:
            lines.append(
                f"  - {row['task_id']} / {row['method']}: {row['detail'] or UPSTREAM_ABORT_WARNING}"
            )
    broken = [row for row in document["rows"] if row["status"] != "OK"]
    for row in broken:
        lines.append(f"- {row['task_id']} / {row['method']}: {row['status']} ({row['detail'] or row['error_code']})")
    return "\n".join(lines) + "\n"
