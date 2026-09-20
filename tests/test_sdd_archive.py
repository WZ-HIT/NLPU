from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch import pilot_cli
from batch.archive import layout, snapshot
from batch.archive.verify import verify as archive_verify
from batch.archive.viewer import ViewerUnavailable
from batch.core import BatchError, canonical_sha256, sha256_file
from batch.orchestrator import Ledger, orchestrate

LEDGER_SCHEMA = "schemas/batch-ledger-event-v1.schema.json"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class ArchiveFixture:
    """A miniature bench that the real viewer, ledger, and archive all accept.

    The schemas and the viewer script are copied from the real bench rather than
    faked. That is the point: the trigger is only interesting if it runs against
    the same discovery rules, the same ledger chain validation, and the same
    detection prerequisite chain that production uses.
    """

    TASK_ID = "owner__repo__pr42"
    BATCH_ID = "fixture-batch-v1"
    METHOD = "openspec"
    DETECT_RUN = "detect-1"
    UPDATE_RUN = "update-1"
    UPDATE_MODE = "sealed-detect"
    BASE_SHA = "a" * 40

    def __init__(self, root: Path, *, updates: bool = False, orchestrate: bool = False) -> None:
        self.repository_root = root
        self.bench = root / "sdd-bench/scrapy-sdd"
        self.task_root = self.bench / "tasks" / self.TASK_ID
        self.run_root = self.bench / "batch/runs" / self.BATCH_ID
        self.updates = updates
        shutil.copytree(BENCH / "schemas", self.bench / "schemas")
        (self.bench / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy2(BENCH / "tools/sdd-results.py", self.bench / "tools/sdd-results.py")
        self._write_task()
        if orchestrate:
            self._write_approval()
        self.config_path = self.bench / "batch/pilot/fixture.json"
        write_json(self.config_path, self._config())
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(
            self.run_root / "ledger.jsonl", self.BATCH_ID, self.bench / LEDGER_SCHEMA
        )
        self._write_sealed_input()

    # -- construction ------------------------------------------------------

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
        (self.task_root / "experiment-inputs").mkdir(parents=True, exist_ok=True)
        (self.task_root / "experiment-inputs/task.md").write_text(
            "Task input\n", encoding="utf-8"
        )

    def _write_approval(self) -> None:
        plan_id = "fixture-plan-v1"
        plan = self.repository_root / "output/plans/fixture.json"
        write_json(
            plan,
            {"plan_id": plan_id, "tasks": [{"task_id": self.TASK_ID, "baseline": {"base_sha": self.BASE_SHA}}]},
        )
        report = self.repository_root / "output/reports/fixture.json"
        write_json(
            report,
            {
                "status": "READY",
                "plan": {"explicitly_approved_plan_id": plan_id, "sha256": sha256_file(plan)},
            },
        )
        self.approved_plan = {
            "plan_id": plan_id,
            "path": plan.relative_to(self.repository_root).as_posix(),
            "sha256": sha256_file(plan),
            "provision_report_path": report.relative_to(self.repository_root).as_posix(),
            "provision_report_sha256": sha256_file(report),
        }

    def _config(self) -> dict:
        methods = {
            "method": self.METHOD,
            "detect": {"run_id": self.DETECT_RUN},
            "updates": (
                [{
                    "run_id": self.UPDATE_RUN,
                    "mode": self.UPDATE_MODE,
                    "policy": {"path": "unused.json", "sha256": "1" * 64},
                }]
                if self.updates
                else []
            ),
        }
        task_entry = {
            "task_id": self.TASK_ID,
            "task_manifest": {
                "path": (self.task_root / "task.json").relative_to(self.repository_root).as_posix(),
                "sha256": sha256_file(self.task_root / "task.json"),
            },
            "methods": [methods],
        }
        config: dict = {
            "schema_version": 1,
            "batch_id": self.BATCH_ID,
            "tasks": [task_entry],
        }
        if hasattr(self, "approved_plan"):
            config["approved_plan"] = self.approved_plan
        return config

    def _write_sealed_input(self) -> None:
        """The Detect seal Update consumes, byte-identical to a detect execution."""
        planning = self.task_root / "runs" / self.METHOD / "update/sealed-input/planning-artifacts"
        planning.mkdir(parents=True, exist_ok=True)
        (planning / "spec.md").write_text("VISIBLE_SPEC\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "manifest_type": "SEALED_DETECTION",
            "task_id": self.TASK_ID,
            "method": self.METHOD,
            "base_sha": self.BASE_SHA,
            "producer": {
                "kind": "agent",
                "stage": "detect",
                "run_id": self.DETECT_RUN,
                "session_sha256": "b" * 64,
            },
            "task_input_sha256": sha256_file(self.task_root / "experiment-inputs/task.md"),
            "candidates": [
                {"path": "tests/test_feature.py", "symbols": ["test_feature"], "reason": "candidate"}
            ],
            "planning_artifacts": {
                "file_count": len(self._planning_entries(planning)),
                "manifest_sha256": canonical_sha256(self._planning_entries(planning)),
            },
            "seal": {"algorithm": "sha256-canonical-json-without-seal", "payload_sha256": ""},
        }
        payload = dict(manifest)
        payload.pop("seal")
        manifest["seal"]["payload_sha256"] = canonical_sha256(payload)
        write_json(
            self.task_root / "runs" / self.METHOD / "update/sealed-input/detection-manifest.json",
            manifest,
        )

    @staticmethod
    def _planning_entries(root: Path) -> list[dict]:
        return [
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ]

    # -- state transitions -------------------------------------------------

    def _target(self, stage: str) -> dict:
        return {
            "task_id": self.TASK_ID,
            "method": self.METHOD,
            "stage": stage,
            "run_id": self.DETECT_RUN if stage == "detect" else self.UPDATE_RUN,
            "mode": None if stage == "detect" else self.UPDATE_MODE,
        }

    def append(self, stage: str, state: str, attempt: int = 1) -> None:
        self.ledger.append(stage, self._target(stage), state, attempt, {"fixture": True})

    def seal_detect(self, attempt: int = 1) -> None:
        execution = (
            self.task_root / "runs" / self.METHOD / "detect/executions"
            / self.DETECT_RUN / f"attempt-{attempt}"
        )
        write_json(
            execution / "detect-summary.json",
            {"status": "SEALED", "task_id": self.TASK_ID, "method": self.METHOD},
        )
        self.append("detect", "DETECT_SEALED", attempt)

    def seal_update(self, attempt: int = 1) -> None:
        execution = (
            self.task_root / "runs" / self.METHOD / "update/executions"
            / self.UPDATE_RUN / f"attempt-{attempt}" / f"mode-{self.UPDATE_MODE}"
        )
        write_json(
            execution / "update-summary.json",
            {
                "status": "SEALED",
                "task_id": self.TASK_ID,
                "method": self.METHOD,
                "update_mode": self.UPDATE_MODE,
            },
        )
        self.append("update", "UPDATE_SEALED", attempt)

    def fail_detect(self, attempt: int = 1) -> None:
        """A concluded-but-failed target: no execution directory ever exists."""
        self.append("detect", "FAILED", attempt)

    def seal_everything(self) -> None:
        self.seal_detect()
        if self.updates:
            self.seal_update()

    # -- observations ------------------------------------------------------

    def archive_root(self) -> Path:
        return layout.archive_root(self.bench)

    def manifest(self) -> dict:
        return json.loads(layout.manifest_path(self.bench).read_text(encoding="utf-8"))

    def html_files(self) -> list[Path]:
        return sorted(self.archive_root().rglob("*.html"))

    def archive(self, **kwargs):
        return snapshot.archive_batch(
            bench=self.bench,
            repository_root=self.repository_root,
            batch_id=self.BATCH_ID,
            config_path=self.config_path,
            **kwargs,
        )


class ArchiveTriggerTests(unittest.TestCase):
    def test_sealed_config_archives_overview_and_every_pr_card(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            result = fixture.archive()

            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(result["outcome"], "SEALED")
            self.assertEqual(
                sorted(item["experiment_id"] for item in result["snapshots"]),
                [fixture.BATCH_ID, f"{fixture.BATCH_ID}/{fixture.TASK_ID}"],
            )
            files = fixture.html_files()
            self.assertEqual(len(files), 2)
            document = fixture.manifest()
            self.assertEqual(document["snapshot_count"], 2)
            for record in document["snapshots"]:
                self.assertEqual(
                    record["html_sha256"], sha256_file(fixture.repository_root / record["path"])
                )
                self.assertEqual(len(record["content_sha256"]), 64)
                self.assertTrue((fixture.repository_root / record["path"]).is_file())

    def test_detect_only_config_seals_without_any_update_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), updates=False)
            fixture.seal_detect()
            result = fixture.archive()

            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(result["outcome"], "SEALED")
            self.assertEqual(result["target_count"], 1)
            for record in fixture.manifest()["snapshots"]:
                self.assertEqual([item["stage"] for item in record["targets"]], ["detect"])

    def test_failed_batch_is_archived_with_outcome_failed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.fail_detect()
            result = fixture.archive()

            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(result["outcome"], "FAILED")
            for record in fixture.manifest()["snapshots"]:
                self.assertEqual(record["outcome"], "FAILED")
                self.assertEqual(record["targets"][0]["state"], "FAILED")

    def test_dry_run_ready_batch_does_not_trigger(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.ledger.append(
                "dry-run", fixture._target("detect"), "DRY_RUN_READY", 1, {"fixture": True}
            )
            result = fixture.archive()

            self.assertEqual(result["status"], "SKIPPED")
            self.assertEqual(result["reason"], "NOT_SETTLED")
            self.assertFalse(fixture.archive_root().exists())

    def test_incomplete_targets_are_reported_as_pending(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), updates=True)
            fixture.seal_detect()
            result = fixture.archive()

            self.assertEqual(result["status"], "SKIPPED")
            self.assertEqual(result["pending_count"], 1)
            self.assertTrue(result["pending"][0].endswith(":update:update-1:sealed-detect"))

    def test_force_archives_an_incomplete_experiment_and_records_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), updates=True)
            fixture.seal_detect()
            result = fixture.archive(force=True)

            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(result["outcome"], "INCOMPLETE")
            for record in fixture.manifest()["snapshots"]:
                self.assertEqual(record["outcome"], "INCOMPLETE")
            states = {
                item["state"] for item in fixture.manifest()["snapshots"][0]["targets"]
            }
            self.assertIn("NOT_RECORDED", states)


class ArchiveIdempotencyTests(unittest.TestCase):
    def test_rerun_unchanged_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            self.assertEqual(fixture.archive()["status"], "ARCHIVED")
            before = {path: path.stat().st_mtime_ns for path in fixture.html_files()}

            second = fixture.archive()

            self.assertEqual(second["status"], "UNCHANGED")
            self.assertEqual(len(second["unchanged"]), 2)
            self.assertEqual(
                {path: path.stat().st_mtime_ns for path in fixture.html_files()}, before
            )
            self.assertEqual(fixture.manifest()["snapshot_count"], 2)

    def test_resume_skip_events_do_not_invalidate_an_existing_snapshot(self) -> None:
        """The ledger grows, its meaning does not, so the snapshot must not churn."""
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            self.assertEqual(fixture.archive()["status"], "ARCHIVED")
            recorded = fixture.manifest()["snapshots"][0]
            ledger_before = sha256_file(fixture.run_root / "ledger.jsonl")

            fixture.append("detect", "SKIPPED_RESUME")

            self.assertNotEqual(sha256_file(fixture.run_root / "ledger.jsonl"), ledger_before)
            self.assertEqual(fixture.archive()["status"], "UNCHANGED")
            self.assertEqual(fixture.manifest()["snapshot_count"], 2)
            self.assertEqual(
                fixture.manifest()["snapshots"][0]["snapshot_id"], recorded["snapshot_id"]
            )

    def test_changed_result_adds_a_new_snapshot_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_detect()
            fixture.archive()
            first = fixture.manifest()["snapshots"][0]
            original_bytes = (fixture.repository_root / first["path"]).read_bytes()

            fixture.seal_detect(attempt=2)
            result = fixture.archive()

            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(len(fixture.html_files()), 4)  # two cards, twice over
            records = fixture.manifest()["snapshots"]
            self.assertEqual(len(records), 4)
            moved = [item for item in records if item["experiment_id"] == first["experiment_id"]]
            self.assertEqual(moved[-1]["supersedes"], first["snapshot_id"])
            self.assertEqual((fixture.repository_root / first["path"]).read_bytes(), original_bytes)

    def test_refresh_forces_a_fresh_render_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            fixture.archive()
            result = fixture.archive(refresh=True)

            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(len(fixture.html_files()), 4)
            rewritten = {item["snapshot_id"] for item in result["snapshots"]}
            self.assertEqual(
                {
                    item["reason"]
                    for item in fixture.manifest()["snapshots"]
                    if item["snapshot_id"] in rewritten
                },
                {"refresh"},
            )

    def test_selected_archive_appends_without_touching_earlier_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            snapshot.archive_selected(
                bench=fixture.bench,
                repository_root=fixture.repository_root,
                selectors=[f"{fixture.BATCH_ID}/{fixture.TASK_ID}"],
            )
            first = fixture.manifest()["snapshots"]
            self.assertEqual(len(first), 1)

            fixture.seal_detect(attempt=2)
            result = snapshot.archive_selected(
                bench=fixture.bench,
                repository_root=fixture.repository_root,
                selectors=[f"{fixture.BATCH_ID}/{fixture.TASK_ID}"],
            )

            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(result["card_count"], 1)
            document = fixture.manifest()
            self.assertEqual(document["snapshots"][:1], first)
            self.assertEqual(
                document["snapshots"][1]["supersedes"], first[0]["snapshot_id"]
            )

    def test_unsettled_refusal_is_loud_when_named_and_quiet_when_sweeping(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), updates=True)
            fixture.seal_detect()

            with self.assertRaises(BatchError) as caught:
                snapshot.archive_selected(
                    bench=fixture.bench,
                    repository_root=fixture.repository_root,
                    selectors=[fixture.BATCH_ID],
                )
            self.assertEqual(caught.exception.as_dict()["code"], "EXPERIMENT_NOT_SEALED")

            # --all sweeps, so an unfinished batch in the middle of one is not an error.
            swept = snapshot.archive_selected(
                bench=fixture.bench,
                repository_root=fixture.repository_root,
                everything=True,
            )
            self.assertEqual(swept["status"], "SKIPPED")
            self.assertFalse(layout.manifest_path(fixture.bench).is_file())


class ArchiveFailureIsolationTests(unittest.TestCase):
    def test_missing_viewer_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            (fixture.bench / "tools/sdd-results.py").unlink()

            with self.assertRaises(ViewerUnavailable) as caught:
                fixture.archive()
            self.assertEqual(caught.exception.as_dict()["code"], "VIEWER_UNAVAILABLE")

    def test_archive_failure_does_not_change_the_orchestrate_summary_or_exit_code(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), orchestrate=True)
            fixture.seal_everything()
            (fixture.bench / "tools/sdd-results.py").unlink()

            with mock.patch.object(pilot_cli, "BENCH", fixture.bench), mock.patch.object(
                pilot_cli, "ROOT", fixture.repository_root
            ):
                code = pilot_cli.run(["detect", "--config", str(fixture.config_path), "--resume"])

            self.assertEqual(code, 0)
            self.assertFalse(layout.manifest_path(fixture.bench).is_file())
            log = layout.error_log_path(fixture.bench)
            self.assertTrue(log.is_file())
            self.assertIn(fixture.BATCH_ID, log.read_text(encoding="utf-8"))

    def test_disabled_archive_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), orchestrate=True)
            fixture.seal_everything()

            summary = orchestrate(
                command="detect",
                config_path=fixture.config_path,
                bench=fixture.bench,
                repository_root=fixture.repository_root,
                dry_run=False,
                resume=True,
                retries=set(),
                task_ids=set(),
                methods=set(),
                modes=set(),
                archive=False,
            )

            self.assertEqual(summary["archive"]["status"], "DISABLED")
            self.assertFalse(fixture.archive_root().exists())


class ArchiveOrchestrateIntegrationTests(unittest.TestCase):
    def test_auto_trigger_fires_at_the_end_of_orchestrate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), orchestrate=True)
            fixture.seal_everything()

            summary = orchestrate(
                command="detect",
                config_path=fixture.config_path,
                bench=fixture.bench,
                repository_root=fixture.repository_root,
                dry_run=False,
                resume=True,
                retries=set(),
                task_ids=set(),
                methods=set(),
                modes=set(),
            )

            self.assertEqual(summary["status"], "READY")
            self.assertEqual(summary["archive"]["status"], "ARCHIVED")
            self.assertEqual(summary["archive"]["batch_id"], fixture.BATCH_ID)
            self.assertTrue(layout.manifest_path(fixture.bench).is_file())
            self.assertEqual(len(fixture.html_files()), 2)

    def test_status_command_never_archives(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), orchestrate=True)
            fixture.seal_everything()

            summary = orchestrate(
                command="status",
                config_path=fixture.config_path,
                bench=fixture.bench,
                repository_root=fixture.repository_root,
                dry_run=False,
                resume=False,
                retries=set(),
                task_ids=set(),
                methods=set(),
                modes=set(),
            )

            self.assertNotIn("archive", summary)
            self.assertFalse(fixture.archive_root().exists())

    def test_dry_run_never_archives(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), orchestrate=True)
            fixture.seal_everything()

            summary = orchestrate(
                command="detect",
                config_path=fixture.config_path,
                bench=fixture.bench,
                repository_root=fixture.repository_root,
                dry_run=True,
                resume=True,
                retries=set(),
                task_ids=set(),
                methods=set(),
                modes=set(),
            )

            self.assertTrue(summary["dry_run"])
            self.assertNotIn("archive", summary)
            self.assertFalse(fixture.archive_root().exists())


class ArchiveContentAndCliTests(unittest.TestCase):
    def test_archive_directory_contains_only_html_and_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            fixture.archive()

            names = {
                path.name
                for path in fixture.archive_root().rglob("*")
                if path.is_file()
            }
            allowed = {layout.MANIFEST_NAME, layout.MANIFEST_LOCK_NAME, layout.ERROR_LOG_NAME}
            self.assertTrue(names <= allowed | {path.name for path in fixture.html_files()})
            for forbidden in ("ledger.jsonl", "final", "evaluation", "detection-manifest.json"):
                self.assertNotIn(forbidden, names)
                self.assertEqual(list(fixture.archive_root().rglob(forbidden)), [])

    def test_snapshots_are_self_contained(self) -> None:
        """Nothing is fetched when the page is opened, so the file survives its source.

        The page still names the absolute execution directory it was rendered
        from, and that path will dangle once the bench's ``tasks/`` tree is
        archived away. That is a breadcrumb, not a dependency: it is rendered
        inside a ``<code>`` element by the existing viewer, which this feature
        deliberately does not modify.
        """
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            fixture.archive()

            for path in fixture.html_files():
                html = path.read_text(encoding="utf-8")
                external = re.findall(r'(?:src|href)="(?!#)([^"]+)"', html)
                self.assertEqual(external, [], f"{path.name} references {external}")
                self.assertIn("<style>", html)
                self.assertIn("<script>", html)

    def test_verify_passes_then_reports_a_tampered_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            fixture.archive()

            result = archive_verify(fixture.bench, fixture.repository_root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["failed_count"], 0)

            victim = fixture.html_files()[0]
            victim.write_text(victim.read_text(encoding="utf-8") + "<!-- tampered -->", encoding="utf-8")

            tampered = archive_verify(fixture.bench, fixture.repository_root)
            self.assertEqual(tampered["status"], "FAIL")
            self.assertEqual(tampered["failed_count"], 1)
            self.assertIn("sha256 differs", json.dumps(tampered["checks"]))

    def test_cli_envelope_and_exit_codes(self) -> None:
        from batch import archive_cli

        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary))
            fixture.seal_everything()
            bench = ["--bench-root", str(fixture.bench)]

            self.assertEqual(archive_cli.run([*bench, "status"]), 0)
            self.assertEqual(archive_cli.run([*bench, "list"]), 0)
            self.assertEqual(
                archive_cli.run([*bench, "archive", "--experiment", fixture.BATCH_ID]), 0
            )
            self.assertEqual(archive_cli.run([*bench, "verify"]), 0)
            # A selector that matches nothing is refused, not crashed.
            self.assertEqual(
                archive_cli.run([*bench, "archive", "--experiment", "no-such-experiment"]), 2
            )

    def test_cli_refuses_an_unconcluded_experiment_and_force_overrides_it(self) -> None:
        from batch import archive_cli

        with tempfile.TemporaryDirectory(prefix="sdd-archive-") as temporary:
            fixture = ArchiveFixture(Path(temporary), updates=True)
            fixture.seal_detect()
            bench = ["--bench-root", str(fixture.bench)]

            self.assertEqual(
                archive_cli.run([*bench, "archive", "--experiment", fixture.BATCH_ID]), 2
            )
            self.assertFalse(layout.manifest_path(fixture.bench).is_file())

            self.assertEqual(
                archive_cli.run(
                    [*bench, "archive", "--experiment", fixture.BATCH_ID, "--force"]
                ),
                0,
            )
            self.assertEqual(
                {item["outcome"] for item in fixture.manifest()["snapshots"]}, {"INCOMPLETE"}
            )


class ArchiveProductionGuardTests(unittest.TestCase):
    """Read-only guards against the real bench, so the design cannot drift."""

    def test_real_sealed_batch_satisfies_the_trigger_and_the_incomplete_one_does_not(self) -> None:
        from batch.archive import viewer

        loaded = viewer.module(BENCH)
        terminal = set(loaded.TERMINAL_STATES)

        sealed = viewer.overview_experiment(
            BENCH, BENCH / "batch/pilot/scrapy-3pr-both-pilot-v1.json", "scrapy-3pr-both-pilot-v1"
        )
        state = snapshot.settlement(loaded.batch_targets(sealed, BENCH), terminal)
        self.assertTrue(state["settled"])
        self.assertEqual(state["outcome"], "SEALED")
        self.assertEqual(len(viewer.batch_cards(BENCH, "scrapy-3pr-both-pilot-v1")), 4)

        pending = viewer.overview_experiment(
            BENCH, BENCH / "batch/pilot/pr8073-pilot.json", "pr8073-pilot-v1"
        )
        pending_state = snapshot.settlement(loaded.batch_targets(pending, BENCH), terminal)
        self.assertFalse(pending_state["settled"])
        self.assertEqual(len(pending_state["pending"]), 3)

    def test_real_card_digests_are_stable_and_distinct(self) -> None:
        from batch.archive import viewer

        cards = viewer.batch_cards(BENCH, "scrapy-3pr-both-pilot-v1")
        self.assertEqual(len(cards), 4)
        digests = {}
        for card in cards:
            rows = snapshot.target_rows(card, BENCH, BENCH.parents[1])
            first = snapshot.card_content_sha(card, BENCH, BENCH.parents[1], rows)
            second = snapshot.card_content_sha(card, BENCH, BENCH.parents[1], rows)
            self.assertEqual(first, second)
            digests[card.experiment_id] = first
        self.assertEqual(len(set(digests.values())), 4)


if __name__ == "__main__":
    unittest.main()
