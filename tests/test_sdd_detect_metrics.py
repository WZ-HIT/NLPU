from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch import detect_metrics, detect_metrics_cli
from batch.core import BatchError, canonical_sha256, sha256_file
from batch.orchestrator import Ledger

LEDGER_SCHEMA = "schemas/batch-ledger-event-v1.schema.json"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def run_cli(argv: list[str]) -> int:
    """Invoke the CLI for its exit code; its JSON envelope is swallowed.

    The envelope is the CLI's product, not the assertion, and printing every
    document a test computes buries the suite's own output.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        return detect_metrics_cli.run(argv)


class MetricsFixture:
    """A miniature bench the real ledger, viewer, and scorer all accept.

    The schemas and ``tools/sdd-results.py`` are copied from the real bench, and
    ``batch/orchestrator.Ledger`` writes the ledger, so discovery, hash-chain
    validation and target resolution are the production rules rather than a
    second implementation of them that could agree with a bug.
    """

    TASK_ID = "owner__repo__pr42"
    BATCH_ID = "fixture-detect-v1"
    BASE_SHA = "a" * 40

    def __init__(self, root: Path, methods: tuple[str, ...] = ("openspec",)) -> None:
        self.repository_root = root
        self.bench = root / "sdd-bench/scrapy-sdd"
        self.task_root = self.bench / "tasks" / self.TASK_ID
        self.run_root = self.bench / "batch/runs" / self.BATCH_ID
        self.methods = list(methods)
        shutil.copytree(BENCH / "schemas", self.bench / "schemas")
        (self.bench / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy2(BENCH / "tools/sdd-results.py", self.bench / "tools/sdd-results.py")
        self._write_task()
        self.config_path = self.bench / "batch/pilot/fixture.json"
        write_json(self.config_path, self._config())
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(
            self.run_root / "ledger.jsonl", self.BATCH_ID, self.bench / LEDGER_SCHEMA
        )

    # -- construction ------------------------------------------------------

    def sibling(
        self, *, task_id: str, batch_id: str, methods: tuple[str, ...] = ("openspec",)
    ) -> "MetricsFixture":
        """A second batch over the same bench, with its own task, config and ledger.

        A rollup is a statement about several batches of *one* bench, so this
        cannot be two fixtures over two temporary repositories: the union is only
        meaningful because both sources were scored against the same gold and the
        same schemas. Sharing the bench means sharing the copied schemas too,
        which is why this builds the object rather than re-running ``__init__``.
        """
        other = object.__new__(type(self))
        other.repository_root = self.repository_root
        other.bench = self.bench
        other.methods = list(methods)
        other.TASK_ID = task_id
        other.BATCH_ID = batch_id
        other.task_root = other.bench / "tasks" / task_id
        other.run_root = other.bench / "batch/runs" / batch_id
        other._write_task()
        other.config_path = other.bench / "batch/pilot" / f"{batch_id}.json"
        write_json(other.config_path, other._config())
        other.run_root.mkdir(parents=True, exist_ok=True)
        other.ledger = Ledger(other.run_root / "ledger.jsonl", batch_id, other.bench / LEDGER_SCHEMA)
        return other

    def _write_task(self) -> None:
        write_json(
            self.task_root / "task.json",
            {
                "task_id": self.TASK_ID,
                "pr_id": 42,
                "title": "Escape <candidate> safely",
                "baseline": {"base_sha": self.BASE_SHA},
            },
        )

    def _config(self) -> dict:
        return {
            "schema_version": 1,
            "batch_id": self.BATCH_ID,
            "tasks": [
                {
                    "task_id": self.TASK_ID,
                    "task_manifest": {
                        "path": (self.task_root / "task.json")
                        .relative_to(self.repository_root)
                        .as_posix(),
                        "sha256": sha256_file(self.task_root / "task.json"),
                    },
                    "methods": [
                        {"method": method, "detect": {"run_id": self.run_id(method)}, "updates": []}
                        for method in self.methods
                    ],
                }
            ],
        }

    @staticmethod
    def run_id(method: str) -> str:
        return f"{method}-detect-1"

    def execution(self, method: str, attempt: int = 1) -> Path:
        return (
            self.task_root / "runs" / method / "detect/executions"
            / self.run_id(method) / f"attempt-{attempt}"
        )

    # -- state transitions -------------------------------------------------

    def _append(self, method: str, state: str, attempt: int = 1) -> None:
        self.ledger.append(
            "detect",
            {
                "task_id": self.TASK_ID,
                "method": method,
                "stage": "detect",
                "run_id": self.run_id(method),
                "mode": None,
            },
            state,
            attempt,
            {"fixture": True},
        )

    def manifest(
        self,
        method: str = "openspec",
        *,
        candidates: list | None = None,
        task_id: str | None = None,
        manifest_type: str | None = None,
    ) -> dict:
        document = {
            "schema_version": 1,
            "manifest_type": manifest_type or "SEALED_DETECTION",
            "task_id": task_id or self.TASK_ID,
            "method": method,
            "base_sha": self.BASE_SHA,
            "producer": {
                "kind": "agent",
                "stage": "detect",
                "run_id": self.run_id(method),
                "session_sha256": "b" * 64,
            },
            "task_input_sha256": "c" * 64,
            "candidates": (
                candidates
                if candidates is not None
                else [{"path": "tests/test_a.py", "symbols": ["test_a"], "reason": "fixture"}]
            ),
            "planning_artifacts": {"file_count": 0, "manifest_sha256": "d" * 64},
            "seal": {"algorithm": "sha256-canonical-json-without-seal", "payload_sha256": ""},
        }
        payload = dict(document)
        payload.pop("seal")
        document["seal"]["payload_sha256"] = canonical_sha256(payload)
        return document

    def seal_detect(
        self, method: str = "openspec", *, attempt: int = 1, document: dict | None = None
    ) -> None:
        """Seal one detect target, writing the manifest where a run really leaves it.

        The manifest is written twice on purpose. ``update/sealed-input`` is the
        copy the Update stage consumes and the copy a re-run displaces;
        ``detect/executions/<run>/attempt-N`` is the one the ledger's current
        attempt names, and the one ``batch/detect_metrics.py`` reads. They are
        byte-identical in production, so a fixture that wrote only one of them
        would let the reader and the producer drift apart unnoticed.
        """
        written = document or self.manifest(method)
        execution = self.execution(method, attempt)
        write_json(execution / "detection-manifest.json", written)
        write_json(
            execution / "detect-summary.json",
            {"status": "SEALED", "task_id": self.TASK_ID, "method": method},
        )
        write_json(
            self.task_root / "runs" / method / "update/sealed-input/detection-manifest.json",
            written,
        )
        self._append(method, "DETECT_SEALED", attempt)

    def fail_detect(self, method: str = "openspec", *, attempt: int = 1) -> None:
        """A concluded-but-failed target: no execution directory ever exists."""
        self._append(method, "FAILED", attempt)

    def fail_detect_upstream_abort(
        self,
        method: str = "openspec",
        *,
        attempt: int = 1,
        message: str = detect_metrics.UPSTREAM_ABORT_SIGNATURES[0],
        state: str = "FAILED",
    ) -> None:
        """A failed target whose Agent session was cut off by the provider.

        The distinction from ``fail_detect`` is the whole point: this run did
        leave an execution directory behind -- the session log is exactly what
        a cut-off run produces -- and it never sealed, so no manifest exists.
        """
        execution = self.execution(method, attempt)
        execution.mkdir(parents=True, exist_ok=True)
        (execution / "rendered-compose.yaml").write_text("services: {}\n", encoding="utf-8")
        (execution / "agent.jsonl").write_text(
            "\n".join([
                json.dumps({"type": "item.completed", "item": {"id": "item_1", "status": "completed"}}),
                json.dumps({"type": "error", "message": message}),
                json.dumps({"type": "turn.failed", "error": {"message": message}}),
            ]) + "\n",
            encoding="utf-8",
        )
        self._append(method, state, attempt)

    def write_gold(
        self,
        files: list[str],
        *,
        task_id: str | None = None,
        store_type: str = "HOST_ONLY_GOLD",
    ) -> Path:
        path = self.bench / "batch/gold" / (task_id or self.TASK_ID) / "gold-store.json"
        write_json(
            path,
            {
                "schema_version": 1,
                "store_type": store_type,
                "task_id": task_id or self.TASK_ID,
                "classification": "TEST_ONLY_PR",
                "gold_target_files": files,
                "gold_target_symbols": [],
            },
        )
        return path

    def gold_path(self) -> Path:
        return self.bench / "batch/gold" / self.TASK_ID / "gold-store.json"

    # -- observations ------------------------------------------------------

    def compute(self) -> dict:
        return detect_metrics.compute(self.bench, self.BATCH_ID)

    def check(self, **kwargs) -> dict:
        return detect_metrics.check(self.bench, self.BATCH_ID, **kwargs)

    def row(self, document: dict, method: str = "openspec") -> dict:
        return next(row for row in document["rows"] if row["method"] == method)

    def report_path(self) -> Path:
        return detect_metrics.document_path(self.bench, self.BATCH_ID)


class DetectMetricsScoringTests(unittest.TestCase):
    def test_exact_hit_scores_perfect_precision_and_recall(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["tests/test_a.py"])

            row = fixture.row(fixture.compute())

            self.assertEqual(row["status"], "OK")
            self.assertEqual(row["metrics"]["tp"], 1)
            self.assertEqual(row["metrics"]["predicted_count"], 1)
            self.assertEqual(row["metrics"]["precision"], 1.0)
            self.assertEqual(row["metrics"]["recall"], 1.0)

    def test_over_reporting_lowers_the_hit_rate_but_not_recall(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect(
                document=fixture.manifest(
                    candidates=[
                        {"path": "tests/test_a.py", "symbols": ["test_a"], "reason": "hit"},
                        {"path": "tests/test_b.py", "symbols": ["test_b"], "reason": "extra"},
                    ]
                )
            )
            fixture.write_gold(["tests/test_a.py"])

            row = fixture.row(fixture.compute())

            self.assertEqual((row["metrics"]["tp"], row["metrics"]["predicted_count"]), (1, 2))
            self.assertEqual(row["metrics"]["precision"], 0.5)
            self.assertEqual(row["metrics"]["recall"], 1.0)
            self.assertEqual(row["extra_files"], ["tests/test_b.py"])
            self.assertEqual(row["matched_files"], ["tests/test_a.py"])

    def test_missing_a_gold_file_lowers_recall_but_not_the_hit_rate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["tests/test_a.py", "tests/test_b.py"])

            row = fixture.row(fixture.compute())

            self.assertEqual(row["metrics"]["precision"], 1.0)
            self.assertEqual(row["metrics"]["recall"], 0.5)
            self.assertEqual(row["missing_gold_files"], ["tests/test_b.py"])

    def test_a_task_without_gold_is_not_scored_as_zero(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()

            document = fixture.compute()
            row = fixture.row(document)

            self.assertEqual(row["status"], "NO_GOLD")
            self.assertFalse(row["gold_available"])
            self.assertIsNone(row["metrics"])
            self.assertFalse(row["scorable"])
            self.assertEqual(document["counts"]["no_gold_count"], 1)
            self.assertEqual(document["counts"]["scorable_count"], 0)
            # The distinction that matters: an unscored row must leave the method
            # average undefined, not drag it to 0.0.
            method = next(item for item in document["methods"] if item["method"] == "openspec")
            self.assertEqual(method["scorable_count"], 0)
            self.assertIsNone(method["hit_rate_micro"])
            self.assertIsNone(method["hit_rate_macro"])

    def test_a_failed_detect_target_becomes_an_error_row_and_does_not_stop_the_batch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary), methods=("openspec", "speckit"))
            fixture.fail_detect("openspec")
            fixture.seal_detect("speckit")
            fixture.write_gold(["tests/test_a.py"])

            document = fixture.compute()

            broken = fixture.row(document, "openspec")
            self.assertEqual(broken["status"], "ERROR")
            self.assertEqual(broken["error_code"], "DETECT_TARGET_UNAVAILABLE")
            self.assertIsNone(broken["metrics"])
            # The surviving target is still scored: one bad target must not erase
            # the batch's numbers, and it must not be dropped from the count either.
            self.assertEqual(fixture.row(document, "speckit")["status"], "OK")
            self.assertEqual(document["status"], "PARTIAL")
            self.assertEqual(document["counts"]["target_count"], 2)
            self.assertEqual(document["counts"]["error_count"], 1)
            self.assertEqual(run_cli([
                "--bench-root", str(fixture.bench), "check", "--batch", fixture.BATCH_ID,
            ]), 0)

    def test_a_provider_aborted_target_is_scored_as_a_miss_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary), methods=("openspec", "speckit"))
            fixture.fail_detect_upstream_abort("openspec")
            fixture.seal_detect("speckit")
            fixture.write_gold(["tests/test_a.py"])

            document = fixture.compute()

            aborted = fixture.row(document, "openspec")
            self.assertEqual(aborted["status"], "OK")
            self.assertIsNone(aborted["error_code"])
            # The row says both things: the run failed, and it is scored anyway.
            self.assertEqual(aborted["state"], "FAILED")
            self.assertIn(detect_metrics.UPSTREAM_ABORT_WARNING, aborted["warnings"])
            self.assertIn(detect_metrics.UPSTREAM_ABORT_SIGNATURES[0], aborted["detail"])
            self.assertTrue(aborted["scorable"])
            self.assertEqual(aborted["predicted_files"], [])
            self.assertEqual(aborted["missing_gold_files"], ["tests/test_a.py"])
            self.assertEqual(aborted["metrics"]["matched_count"], 0)
            self.assertEqual(aborted["metrics"]["precision"], 0.0)
            self.assertEqual(aborted["metrics"]["hit_at_1"], 0)
            # Counted, not dropped: the batch is one miss and one hit, so the
            # ratio is over both targets rather than over the survivor -- and
            # the cause is countable too, without anyone parsing prose.
            self.assertEqual(document["counts"]["target_count"], 2)
            self.assertEqual(document["counts"]["error_count"], 0)
            self.assertEqual(document["counts"]["warning_count"], 1)

    def test_only_the_recorded_provider_abort_is_scored_as_a_miss(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary), methods=("openspec",))
            fixture.fail_detect_upstream_abort(
                "openspec", message="container killed: OCI runtime error"
            )
            fixture.write_gold(["tests/test_a.py"])

            row = fixture.row(fixture.compute(), "openspec")

            # An unknown failure stays an error rather than a zero. The
            # allowlist is what keeps a broken bench from reading as a miss.
            self.assertEqual(row["status"], "ERROR")
            self.assertEqual(row["error_code"], "DETECT_TARGET_UNAVAILABLE")
            self.assertNotIn(detect_metrics.UPSTREAM_ABORT_WARNING, row["warnings"])
            self.assertIsNone(row["metrics"])

    def test_a_target_that_has_not_concluded_is_never_scored_as_a_miss(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary), methods=("openspec",))
            fixture.fail_detect_upstream_abort("openspec", state="DETECT_RUNNING")
            fixture.write_gold(["tests/test_a.py"])

            row = fixture.row(fixture.compute(), "openspec")

            # A run still in flight may yet seal; scoring it now would bank a
            # miss against a target that has not finished.
            self.assertEqual(row["status"], "ERROR")
            self.assertIsNone(row["metrics"])

    def test_a_missing_detection_manifest_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["tests/test_a.py"])
            (fixture.execution("openspec") / "detection-manifest.json").unlink()

            row = fixture.row(fixture.compute())

            self.assertEqual(row["status"], "ERROR")
            self.assertEqual(row["error_code"], "DETECT_MANIFEST_MISSING")

    def test_a_manifest_naming_another_task_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect(
                document=fixture.manifest(task_id="someone__else__pr99")
            )
            fixture.write_gold(["tests/test_a.py"])

            row = fixture.row(fixture.compute())

            self.assertEqual(row["status"], "ERROR")
            self.assertEqual(row["error_code"], "DETECT_MANIFEST_IDENTITY_MISMATCH")

    def test_unsafe_candidates_are_counted_never_raised(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect(
                document=fixture.manifest(
                    candidates=[
                        {"path": "/etc/passwd", "symbols": [], "reason": "absolute"},
                        {"path": "../escape.py", "symbols": [], "reason": "parent"},
                        {"path": "src/app.py", "symbols": [], "reason": "not a test root"},
                        {"path": "tests/test_a.py", "symbols": [], "reason": "first"},
                        {"path": "tests/test_a.py", "symbols": [], "reason": "duplicate"},
                    ]
                )
            )
            fixture.write_gold(["tests/test_a.py"])

            document = fixture.compute()
            row = fixture.row(document)

            self.assertEqual(row["predicted_files"], ["tests/test_a.py"])
            self.assertEqual(row["metrics"]["invalid_count"], 4)
            self.assertEqual(row["status"], "OK")
            self.assertEqual(document["counts"]["invalid_candidate_count"], 4)
            self.assertIn("invalid_candidate_paths_rejected", row["warnings"])

    def test_gold_outside_the_test_roots_is_flagged_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["src/app.py"])

            document = fixture.compute()
            row = fixture.row(document)

            # Unreachable by construction: the candidate side rejects it. Saying so
            # is what stops a structural cap from reading as a detector miss.
            self.assertIn("gold_outside_test_roots", row["warnings"])
            self.assertEqual(row["metrics"]["recall"], 0.0)
            self.assertEqual(document["counts"]["warning_count"], 1)


class DetectMetricsDocumentTests(unittest.TestCase):
    def test_the_same_bench_produces_the_same_bytes_twice(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary), methods=("openspec", "speckit"))
            fixture.seal_detect("openspec")
            fixture.seal_detect("speckit")
            fixture.write_gold(["tests/test_a.py"])

            first = fixture.check()
            before = fixture.report_path().read_bytes()
            second = fixture.check()

            self.assertEqual(before, fixture.report_path().read_bytes())
            self.assertEqual(first["metric_set_sha256"], second["metric_set_sha256"])
            self.assertFalse(second["changed"])
            self.assertEqual(json.dumps(fixture.compute(), sort_keys=True),
                             json.dumps(fixture.compute(), sort_keys=True))

    def test_a_resume_event_changes_the_ledger_bytes_but_not_the_metrics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary), methods=("openspec", "speckit"))
            fixture.seal_detect("openspec")
            fixture.seal_detect("speckit")
            fixture.write_gold(["tests/test_a.py"])
            before = canonical_sha256(fixture.compute())
            ledger_before = (fixture.run_root / "ledger.jsonl").read_bytes()

            fixture._append("speckit", "SKIPPED_RESUME", 2)

            self.assertNotEqual(ledger_before, (fixture.run_root / "ledger.jsonl").read_bytes())
            self.assertEqual(before, canonical_sha256(fixture.compute()))
            self.assertNotIn("ledger", json.dumps(fixture.compute()))

    def test_the_recorded_document_satisfies_its_schema(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["tests/test_a.py"])

            result = fixture.check()
            recorded = json.loads(fixture.report_path().read_text(encoding="utf-8"))

            self.assertEqual(result["status"], "OK")
            detect_metrics._schema_validate(
                recorded, fixture.bench / "schemas/detect-metrics-v1.schema.json"
            )
            self.assertEqual(
                recorded["metric_set_sha256"],
                canonical_sha256({key: value for key, value in recorded.items()
                                  if key != "metric_set_sha256"}),
            )

    def test_no_absolute_path_is_written_into_the_document(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["tests/test_a.py"])

            fixture.check()

            self.assertNotIn(str(fixture.repository_root),
                             fixture.report_path().read_text(encoding="utf-8"))


class DetectMetricsCliTests(unittest.TestCase):
    def test_check_show_and_status_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["tests/test_a.py"])
            argv = ["--bench-root", str(fixture.bench)]

            self.assertEqual(run_cli([*argv, "check", "--batch", fixture.BATCH_ID]), 0)
            self.assertTrue(fixture.report_path().is_file())

            written = detect_metrics.show(fixture.bench, fixture.BATCH_ID)
            shown = run_cli([*argv, "show", "--batch", fixture.BATCH_ID])
            self.assertEqual(shown, 0)
            self.assertEqual(
                written["metric_set_sha256"],
                json.loads(fixture.report_path().read_text(encoding="utf-8"))["metric_set_sha256"],
            )

            listing = detect_metrics.status(fixture.bench)
            self.assertEqual(listing["report_count"], 1)
            self.assertEqual(listing["reports"][0]["batch_id"], fixture.BATCH_ID)
            self.assertEqual(listing["reports"][0]["row_count"], 1)

    def test_dry_run_computes_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["tests/test_a.py"])

            result = fixture.check(dry_run=True)

            self.assertEqual(result["status"], "OK")
            self.assertFalse(result["written"])
            self.assertFalse(fixture.report_path().exists())

    def test_strict_exits_five_on_an_error_row(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.fail_detect()
            argv = ["--bench-root", str(fixture.bench)]

            self.assertEqual(
                run_cli([*argv, "check", "--batch", fixture.BATCH_ID, "--strict"]), 5
            )
            # Missing gold is not a failure of the run, so --strict ignores it.
            fixture2 = MetricsFixture(Path(temporary) / "second")
            fixture2.seal_detect()
            self.assertEqual(
                run_cli(
                    ["--bench-root", str(fixture2.bench), "check", "--batch", fixture2.BATCH_ID, "--strict"]
                ),
                0,
            )

    def test_show_without_a_recorded_report_is_a_clean_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))

            with self.assertRaises(BatchError) as caught:
                detect_metrics.show(fixture.bench, "no-such-batch")

            self.assertEqual(caught.exception.code, "DETECT_METRICS_NOT_FOUND")
            self.assertEqual(
                run_cli([
                    "--bench-root", str(fixture.bench), "show", "--batch", "no-such-batch",
                ]),
                2,
            )

    def test_check_writes_under_log_and_nowhere_else(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.write_gold(["tests/test_a.py"])

            fixture.check()

            # The batch card root is not gitignored, and the card says gold data is
            # excluded, so nothing derived from gold may be written there.
            self.assertFalse((fixture.bench / "batch/viewer-reports").exists())
            self.assertEqual(
                fixture.report_path().parent,
                fixture.bench / "Log/reports/detect-metrics",
            )
            self.assertEqual(fixture.report_path().stat().st_mode & 0o777, 0o600)


class DetectMetricsViewerTests(unittest.TestCase):
    """The viewer must degrade to *absent*, never to wrong or to an exception."""

    def _render(self, fixture: MetricsFixture) -> tuple[str, str]:
        from batch.archive import viewer

        loaded = viewer.module(fixture.bench)
        cards = viewer.batch_cards(fixture.bench, fixture.BATCH_ID)
        overview = next(card for card in cards if card.task_id_filter is None)
        per_pr = next(card for card in cards if card.task_id_filter is not None)
        return (
            loaded.build_html(overview, fixture.bench),
            loaded.build_html(per_pr, fixture.bench),
        )

    def test_cards_render_without_a_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()

            batch_html, pr_html = self._render(fixture)

            self.assertEqual(batch_html.count("Detect 命中率"), 0)
            self.assertEqual(pr_html.count("Detect 命中率"), 0)
            self.assertIn("Read-only view of terminal sealed artifacts", pr_html)

    def test_cards_show_the_rates_and_never_a_file_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect(
                document=fixture.manifest(
                    candidates=[
                        {"path": "tests/test_a.py", "symbols": [], "reason": "hit"},
                        {"path": "tests/test_b.py", "symbols": [], "reason": "extra"},
                    ]
                )
            )
            fixture.write_gold(["tests/test_a.py"])
            fixture.check()

            batch_html, pr_html = self._render(fixture)

            self.assertEqual(pr_html.count("Detect 命中率"), 1)
            self.assertEqual(batch_html.count("Detect 命中率"), 1)
            self.assertIn("50.0%", pr_html)
            self.assertIn("100.0%", pr_html)
            # The card claims gold is excluded, and its output root is not
            # gitignored. Neither the gold file nor the extra candidate may be
            # named in the section this feature adds.
            section = pr_html[pr_html.index("Detect 命中率"):pr_html.index("</section>", pr_html.index("Detect 命中率"))]
            self.assertNotIn("tests/test_a.py", section)
            self.assertNotIn("tests/test_b.py", section)

    def test_an_unscored_task_renders_na_rather_than_zero(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture = MetricsFixture(Path(temporary))
            fixture.seal_detect()
            fixture.check()

            batch_html, pr_html = self._render(fixture)

            self.assertIn("N/A", pr_html)
            self.assertIn("N/A", batch_html)
            self.assertNotIn("0.0%", pr_html)


class DetectMetricsProductionGuardTests(unittest.TestCase):
    """Read-only guards against the real bench, so the design cannot drift.

    These call ``compute`` and never ``check``. Computing is a read; checking
    writes under ``Log/``, and a test suite that writes into the real bench is a
    production change wearing a test's clothes.
    """

    BATCH_ID = "scrapy-3pr-detect-v2"

    def test_real_three_prs_reproduce_the_expected_hit_rates(self) -> None:
        document = detect_metrics.compute(BENCH, self.BATCH_ID)

        expected = {
            ("scrapy__scrapy__pr8064", "openspec"): (1, 1),
            ("scrapy__scrapy__pr8064", "speckit"): (1, 2),
            ("scrapy__scrapy__pr8064", "cc-sdd"): (1, 1),
            ("scrapy__scrapy__pr8067", "openspec"): (1, 2),
            ("scrapy__scrapy__pr8067", "speckit"): (1, 2),
            ("scrapy__scrapy__pr8067", "cc-sdd"): (1, 2),
            ("scrapy__scrapy__pr8073", "openspec"): (2, 5),
            ("scrapy__scrapy__pr8073", "speckit"): (2, 2),
            ("scrapy__scrapy__pr8073", "cc-sdd"): (2, 5),
        }
        observed = {
            (row["task_id"], row["method"]): (row["metrics"]["tp"], row["metrics"]["predicted_count"])
            for row in document["rows"]
        }

        self.assertEqual(observed, expected)
        self.assertEqual(document["status"], "OK")
        self.assertEqual(document["counts"]["error_count"], 0)
        self.assertEqual(document["counts"]["no_gold_count"], 0)
        self.assertEqual(document["counts"]["invalid_candidate_count"], 0)
        self.assertEqual(document["counts"]["warning_count"], 0)

    def test_real_computation_is_deterministic(self) -> None:
        first = detect_metrics.compute(BENCH, self.BATCH_ID)
        second = detect_metrics.compute(BENCH, self.BATCH_ID)

        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_guard_does_not_touch_the_real_bench(self) -> None:
        def snapshot() -> dict[str, tuple[float, int]]:
            state: dict[str, tuple[float, int]] = {}
            for relative in ("batch/gold", "batch/viewer-reports", "Log/reports"):
                root = BENCH / relative
                if not root.is_dir():
                    continue
                for path in sorted(root.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        info = path.stat()
                        state[str(path.relative_to(BENCH))] = (info.st_mtime, info.st_size)
            return state

        before = snapshot()
        detect_metrics.compute(BENCH, self.BATCH_ID)

        self.assertEqual(before, snapshot())


class DetectMetricsRollupTests(unittest.TestCase):
    """The cross-batch union, over two batches of one fixture bench."""

    def _two_batches(self, temporary: str) -> tuple[MetricsFixture, MetricsFixture]:
        """The primary batch scores 1/1; the sibling scores 1/4.

        Deliberately unequal, and deliberately not 1/1 twice: a rollup that
        averaged the two methods would give the same answer as one that pooled
        the rows only when the two are the same size, and that is the bug this
        fixture exists to make impossible to miss.
        """
        fixture = MetricsFixture(Path(temporary))
        other = fixture.sibling(task_id="owner__repo__pr43", batch_id="fixture-detect-v2")
        fixture.seal_detect()
        fixture.write_gold(["tests/test_a.py"])
        other.seal_detect(
            document=other.manifest(
                candidates=[
                    {"path": "tests/test_a.py", "symbols": ["test_a"], "reason": "hit"},
                    {"path": "tests/test_b.py", "symbols": ["test_b"], "reason": "extra"},
                    {"path": "tests/test_c.py", "symbols": ["test_c"], "reason": "extra"},
                    {"path": "tests/test_d.py", "symbols": ["test_d"], "reason": "extra"},
                ]
            )
        )
        other.write_gold(["tests/test_a.py"])
        fixture.check()
        other.check()
        return fixture, other

    def _rollup(self, fixture: MetricsFixture, **kwargs) -> dict:
        return detect_metrics.rollup(
            fixture.bench, [fixture.BATCH_ID, "fixture-detect-v2"], "fixture-union-v1", **kwargs
        )

    def _two_batches_one_aborted(self, temporary: str) -> tuple[MetricsFixture, MetricsFixture]:
        """The sibling's only run was cut off by the provider: a scored zero, not a rate.

        It carries gold and it never sealed, so the row is ``OK`` with a ``0/0``
        cell -- the shape a reader cannot tell apart from a method that looked
        and reported nothing.
        """
        fixture = MetricsFixture(Path(temporary))
        other = fixture.sibling(task_id="owner__repo__pr43", batch_id="fixture-detect-v2")
        fixture.seal_detect()
        fixture.write_gold(["tests/test_a.py"])
        other.fail_detect_upstream_abort("openspec")
        other.write_gold(["tests/test_a.py"])
        fixture.check()
        other.check()
        return fixture, other

    def test_the_union_pools_the_rows_instead_of_averaging_the_sources(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches(temporary)

            result = self._rollup(fixture)

            openspec = next(item for item in result["methods"] if item["method"] == "openspec")
            self.assertEqual(result["counts"]["target_count"], 2)
            self.assertEqual((openspec["a"], openspec["b"]), (2, 5))
            # 2/5 = 0.4. The average of the two source rates, (1.0 + 0.25) / 2,
            # is 0.625 -- the number a rollup must not report.
            self.assertAlmostEqual(openspec["hit_rate_micro"], 0.4)
            self.assertAlmostEqual(openspec["hit_rate_macro"], 0.625)

    def test_the_rollup_names_both_sources_and_carries_their_metric_sets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, other = self._two_batches(temporary)

            result = self._rollup(fixture)

            self.assertEqual([source["batch_id"] for source in result["sources"]],
                             [fixture.BATCH_ID, other.BATCH_ID])
            self.assertEqual([source["row_count"] for source in result["sources"]], [1, 1])
            self.assertEqual(
                [source["metric_set_sha256"] for source in result["sources"]],
                [
                    detect_metrics.show(fixture.bench, fixture.BATCH_ID)["metric_set_sha256"],
                    detect_metrics.show(other.bench, other.BATCH_ID)["metric_set_sha256"],
                ],
            )

    def test_the_recorded_rollup_satisfies_its_schema(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches(temporary)

            self._rollup(fixture)
            recorded = json.loads(
                detect_metrics.rollup_path(fixture.bench, "fixture-union-v1").read_text(encoding="utf-8")
            )

            detect_metrics._schema_validate(
                recorded, fixture.bench / "schemas/detect-metrics-rollup-v1.schema.json"
            )
            self.assertEqual(
                recorded["metric_set_sha256"],
                canonical_sha256({key: value for key, value in recorded.items()
                                  if key != "metric_set_sha256"}),
            )

    def test_the_rollup_schema_reuses_the_batch_row_and_method_definitions(self) -> None:
        """The anti-drift guard: a copied ``$defs`` is a ``$defs`` that drifts.

        The rollup document carries the same row objects as a batch document, so
        the two schemas must agree on what a row is. This asserts on the real
        bench's schemas, not the fixture's, because the fixture copies them.
        """
        batch = json.loads((BENCH / "schemas/detect-metrics-v1.schema.json").read_text(encoding="utf-8"))
        rollup = json.loads(
            (BENCH / "schemas/detect-metrics-rollup-v1.schema.json").read_text(encoding="utf-8")
        )

        for name in ("id", "sha256", "pathList", "row", "metrics", "method"):
            self.assertEqual(rollup["$defs"][name], batch["$defs"][name], name)

    def test_no_absolute_path_is_written_into_the_rollup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches(temporary)

            self._rollup(fixture)

            for path in (
                detect_metrics.rollup_path(fixture.bench, "fixture-union-v1"),
                detect_metrics.rollup_markdown_path(fixture.bench, "fixture-union-v1"),
            ):
                self.assertNotIn(str(fixture.repository_root), path.read_text(encoding="utf-8"))

    def test_the_markdown_names_every_task_and_no_candidate_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, other = self._two_batches(temporary)

            markdown = self._rollup(fixture)["markdown"]

            self.assertIn(fixture.TASK_ID, markdown)
            self.assertIn(other.TASK_ID, markdown)
            # The Markdown is a report, not a leak: it counts files and never
            # names one, which is the same rule the viewer cards follow.
            self.assertNotIn("test_a.py", markdown)

    def test_the_caveats_name_the_provider_aborted_rows_and_why_their_zero_counts(self) -> None:
        """An aborted ``0/0`` must read as a missing answer, not as a method that found nothing.

        Both cells print ``0/0``, and one of them moves the method's hit rate.
        Without this line the table says the two runs are the same observation,
        and the only way to learn otherwise is to go back to the ledger.
        """
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, other = self._two_batches_one_aborted(temporary)

            markdown = self._rollup(fixture)["markdown"]

            caveats = markdown.split("## Caveats")[1]
            self.assertIn(detect_metrics.UPSTREAM_ABORT_WARNING, caveats)
            self.assertIn(other.TASK_ID, caveats)
            self.assertNotIn(fixture.TASK_ID, caveats)
            self.assertIn(detect_metrics.UPSTREAM_ABORT_SIGNATURES[0], caveats)
            self.assertIn("scored as the misses", caveats)

    def test_the_single_file_caveat_does_not_count_a_provider_abort(self) -> None:
        """The two caveats partition the zeros: an abort did not report "at most one file"."""
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches_one_aborted(temporary)

            markdown = self._rollup(fixture)["markdown"]

            self.assertIn("1 of 2 targets reported at most one file", markdown)

    def test_dry_run_computes_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches(temporary)

            result = self._rollup(fixture, dry_run=True)

            self.assertFalse(result["written"])
            self.assertFalse(detect_metrics.rollups_root(fixture.bench).exists())

    def test_a_batch_listed_twice_is_not_a_rollup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches(temporary)

            with self.assertRaises(BatchError) as raised:
                detect_metrics.rollup(
                    fixture.bench, [fixture.BATCH_ID, fixture.BATCH_ID], "fixture-union-v1"
                )

            self.assertEqual(raised.exception.code, "ROLLUP_SOURCE_INVALID")

    def test_a_single_batch_is_not_a_rollup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches(temporary)

            with self.assertRaises(BatchError) as raised:
                detect_metrics.rollup(fixture.bench, [fixture.BATCH_ID], "fixture-union-v1")

            self.assertEqual(raised.exception.code, "ROLLUP_SOURCE_INVALID")

    def test_a_source_that_no_longer_matches_the_bench_is_refused(self) -> None:
        """Stale evidence is refused, never averaged in.

        The recorded document is left alone and the bench moves underneath it --
        which is exactly what an added gold file looks like from here.
        """
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches(temporary)
            fixture.write_gold(["tests/test_a.py", "tests/test_b.py"])

            with self.assertRaises(BatchError) as raised:
                self._rollup(fixture)

            self.assertEqual(raised.exception.code, "ROLLUP_SOURCE_STALE")
            self.assertEqual(raised.exception.details["batch_id"], fixture.BATCH_ID)

    def test_a_source_without_a_recorded_report_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, other = self._two_batches(temporary)
            other.report_path().unlink()

            with self.assertRaises(BatchError) as raised:
                self._rollup(fixture)

            self.assertEqual(raised.exception.code, "DETECT_METRICS_NOT_FOUND")

    def test_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-detect-metrics-") as temporary:
            fixture, _ = self._two_batches(temporary)
            argv = [
                "--bench-root", str(fixture.bench), "rollup",
                "--batch", fixture.BATCH_ID, "--batch", "fixture-detect-v2",
                "--as", "fixture-union-v1",
            ]

            self.assertEqual(run_cli(argv), 0)
            self.assertTrue(detect_metrics.rollup_path(fixture.bench, "fixture-union-v1").is_file())
            self.assertTrue(
                detect_metrics.rollup_markdown_path(fixture.bench, "fixture-union-v1").is_file()
            )
            # A rollup is not a batch report, and `status` must not present it as
            # one: it lists the two scored batches and nothing else.
            listing = detect_metrics.status(fixture.bench)
            self.assertEqual([record["batch_id"] for record in listing["reports"]],
                             [fixture.BATCH_ID, "fixture-detect-v2"])


if __name__ == "__main__":
    unittest.main()
