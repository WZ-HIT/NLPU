from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
MODULE_PATH = BENCH / "tools/sdd-results.py"
SPEC = importlib.util.spec_from_file_location("sdd_results", MODULE_PATH)
assert SPEC and SPEC.loader
sdd_results = importlib.util.module_from_spec(SPEC)
sys.modules["sdd_results"] = sdd_results
SPEC.loader.exec_module(sdd_results)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def overview(experiments: list) -> object:
    """The whole-batch entry, as opposed to one of its per-PR views."""
    return next(item for item in experiments if item.task_id_filter is None)


def write_ledger(path: Path, batch_id: str, events: list[dict[str, object]]) -> None:
    previous = None
    records = []
    for sequence, source in enumerate(events, 1):
        event = {
            "schema_version": 1,
            "batch_id": batch_id,
            "sequence": sequence,
            "recorded_at_utc": "2026-09-18T00:00:00Z",
            "action": source["target"]["stage"],
            **source,
            "previous_event_sha256": previous,
            "details_sha256": "0" * 64,
        }
        event["event_sha256"] = canonical_sha256(event)
        previous = event["event_sha256"]
        records.append(event)
    path.write_text("".join(json.dumps(event) + "\n" for event in records), encoding="utf-8")


class SddResultsBatchFixtureTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> Path:
        bench = root / "sdd-bench/scrapy-sdd"
        repository = root
        task_id = "owner__repo__pr42"
        task_root = bench / "tasks" / task_id
        task_manifest = task_root / "task.json"
        write_json(
            task_manifest,
            {
                "task_id": task_id,
                "pr_id": 42,
                "title": "Escape <candidate> safely",
            },
        )
        relative_manifest = task_manifest.relative_to(repository).as_posix()
        config = {
            "batch_id": "fixture-batch-v1",
            "tasks": [
                {
                    "task_id": task_id,
                    "task_manifest": {"path": relative_manifest, "sha256": sha256_file(task_manifest)},
                    "methods": [
                        {
                            "method": "openspec",
                            "detect": {"run_id": "detect-1"},
                            "updates": [
                                {
                                    "run_id": "update-1",
                                    "mode": "sealed-detect",
                                    "policy": {"path": "unused", "sha256": "1" * 64},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        write_json(bench / "batch/pilot/fixture.json", config)
        run_root = bench / "batch/runs/fixture-batch-v1"
        run_root.mkdir(parents=True)
        events = [
            {
                "state": "FAILED",
                "attempt": 1,
                "target": {
                    "task_id": task_id,
                    "method": "openspec",
                    "stage": "detect",
                    "run_id": "detect-1",
                    "update_mode": None,
                },
            },
            {
                "state": "DETECT_SEALED",
                "attempt": 2,
                "target": {
                    "task_id": task_id,
                    "method": "openspec",
                    "stage": "detect",
                    "run_id": "detect-1",
                    "update_mode": None,
                },
            },
            {
                "state": "UPDATE_SEALED",
                "attempt": 1,
                "target": {
                    "task_id": task_id,
                    "method": "openspec",
                    "stage": "update",
                    "run_id": "update-1",
                    "update_mode": "sealed-detect",
                },
            },
        ]
        write_ledger(run_root / "ledger.jsonl", "fixture-batch-v1", events)

        failed = task_root / "runs/openspec/detect/executions/detect-1/attempt-1"
        failed.mkdir(parents=True)
        (failed / "failed-sentinel.txt").write_text("FAILED_ATTEMPT_SENTINEL", encoding="utf-8")
        detect = task_root / "runs/openspec/detect/executions/detect-1/attempt-2"
        write_json(
            detect / "detection-manifest.json",
            {
                "candidates": [
                    {
                        "path": "tests/test_feature.py",
                        "symbols": ["test_feature"],
                        "reason": "candidate <reason>",
                    }
                ]
            },
        )
        write_json(
            detect / "detect-summary.json",
            {"status": "SEALED", "task_id": task_id, "method": "openspec"},
        )
        (detect / "sdd-artifacts").mkdir()
        (detect / "sdd-artifacts/spec.md").write_text("VISIBLE_SPEC", encoding="utf-8")
        (detect / "agent.jsonl").write_text(
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "VISIBLE_DETECT_MESSAGE"}}) + "\n",
            encoding="utf-8",
        )
        (detect / "workspace").mkdir()
        (detect / "workspace/secret.txt").write_text("WORKSPACE_SENTINEL", encoding="utf-8")

        update = task_root / "runs/openspec/update/executions/update-1/attempt-1/mode-sealed-detect"
        (update / "artifacts").mkdir(parents=True)
        (update / "artifacts/candidate.patch").write_text(
            "diff --git a/tests/test_feature.py b/tests/test_feature.py\n"
            "--- a/tests/test_feature.py\n+++ b/tests/test_feature.py\n"
            "@@ -0,0 +1 @@\n+VISIBLE_PATCH\n",
            encoding="utf-8",
        )
        write_json(update / "artifacts/scope-audit.json", {"violations": []})
        write_json(update / "candidate-modified-files.json", {"files": ["tests/test_feature.py"]})
        write_json(
            update / "update-summary.json",
            {
                "status": "SEALED",
                "task_id": task_id,
                "method": "openspec",
                "update_mode": "sealed-detect",
            },
        )
        (update / "artifacts/agent.jsonl").write_text(
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "VISIBLE_UPDATE_MESSAGE"}}) + "\n",
            encoding="utf-8",
        )
        (update / "workspace").mkdir()
        (update / "workspace/secret.txt").write_text("UPDATE_WORKSPACE_SENTINEL", encoding="utf-8")

        (bench / "batch/gold/task").mkdir(parents=True)
        (bench / "batch/gold/task/secret.txt").write_text("GOLD_SENTINEL", encoding="utf-8")
        (run_root / "evaluation").mkdir()
        (run_root / "evaluation/secret.txt").write_text("EVALUATION_SENTINEL", encoding="utf-8")
        return bench

    def test_discovers_and_renders_only_terminal_batch_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-results-") as temporary:
            bench = self.build_fixture(Path(temporary))
            experiments = sdd_results.discover(bench)
            self.assertEqual(
                [item.experiment_id for item in experiments],
                ["fixture-batch-v1", "fixture-batch-v1/owner__repo__pr42"],
            )
            experiment = experiments[0]
            targets = sdd_results.batch_targets(experiment, bench)
            self.assertEqual(len(targets), 2)
            self.assertEqual(targets[0].attempt, 2)
            batch_html = sdd_results.build_html(experiment, bench)
            self.assertNotIn("VISIBLE_SPEC", batch_html)
            self.assertIn("PR 列表", batch_html)
            html = sdd_results.build_html(next(e for e in experiments if e.task_id_filter), bench)
            for expected in (
                "VISIBLE_SPEC",
                "VISIBLE_DETECT_MESSAGE",
                "VISIBLE_PATCH",
                "VISIBLE_UPDATE_MESSAGE",
                "candidate &lt;reason&gt;",
            ):
                self.assertIn(expected, html)
            for forbidden in (
                "FAILED_ATTEMPT_SENTINEL",
                "WORKSPACE_SENTINEL",
                "UPDATE_WORKSPACE_SENTINEL",
                "GOLD_SENTINEL",
                "EVALUATION_SENTINEL",
            ):
                self.assertNotIn(forbidden, html)

    def test_unsafe_task_manifest_is_not_traversed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-results-") as temporary:
            bench = self.build_fixture(Path(temporary))
            config_path = bench / "batch/pilot/fixture.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["tasks"][0]["task_manifest"]["path"] = "../outside.json"
            write_json(config_path, config)
            experiment = overview(sdd_results.discover(bench))
            targets = sdd_results.batch_targets(experiment, bench)
            self.assertTrue(targets)
            self.assertTrue(all(item.execution is None for item in targets))
            self.assertTrue(all("task manifest" in (item.error or "") for item in targets))
    def test_tampered_ledger_is_not_traversed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-results-") as temporary:
            bench = self.build_fixture(Path(temporary))
            ledger = bench / "batch/runs/fixture-batch-v1/ledger.jsonl"
            records = ledger.read_text(encoding="utf-8").splitlines()
            event = json.loads(records[-1])
            event["attempt"] = 2
            records[-1] = json.dumps(event)
            ledger.write_text("\n".join(records) + "\n", encoding="utf-8")
            experiment = overview(sdd_results.discover(bench))
            targets = sdd_results.batch_targets(experiment, bench)
            self.assertTrue(targets)
            self.assertTrue(all(item.execution is None for item in targets))
            self.assertTrue(all("ledger hash chain" in (item.error or "") for item in targets))

    def test_task_manifest_hash_mismatch_is_not_traversed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-results-") as temporary:
            bench = self.build_fixture(Path(temporary))
            config_path = bench / "batch/pilot/fixture.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["tasks"][0]["task_manifest"]["sha256"] = "f" * 64
            write_json(config_path, config)
            experiment = overview(sdd_results.discover(bench))
            targets = sdd_results.batch_targets(experiment, bench)
            self.assertTrue(targets)
            self.assertTrue(all(item.execution is None for item in targets))
            self.assertTrue(all("manifest hash" in (item.error or "") for item in targets))

    def test_custom_bench_status_uses_custom_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-results-") as temporary:
            bench = self.build_fixture(Path(temporary))
            experiment = overview(sdd_results.discover(bench))
            self.assertEqual(sdd_results.overall_status(experiment, bench), "SEALED")
            output = io.StringIO()
            with redirect_stdout(output):
                sdd_results.print_list([experiment], bench)
            self.assertIn("SEALED", output.getvalue())

    def test_per_pr_view_scopes_targets_and_renders_method_tabs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-results-") as temporary:
            bench = self.build_fixture(Path(temporary))
            experiments = sdd_results.discover(bench)
            self.assertEqual(
                [item.experiment_id for item in experiments],
                ["fixture-batch-v1", "fixture-batch-v1/owner__repo__pr42"],
            )
            child = next(item for item in experiments if item.task_id_filter)
            self.assertEqual(child.batch_id, "fixture-batch-v1")
            self.assertEqual(child.task_id_filter, "owner__repo__pr42")
            self.assertEqual(child.source_kind, "batch")
            targets = sdd_results.batch_targets(child, bench)
            self.assertEqual({item.task_id for item in targets}, {"owner__repo__pr42"})
            self.assertEqual(len(targets), 2)
            self.assertEqual(sdd_results.overall_status(child, bench), "SEALED")
            self.assertEqual(sdd_results.task_id(child), "owner__repo__pr42")
            html = sdd_results.build_html(child, bench)
            for expected in ('data-tab="overview"', 'data-tab="openspec"', "Escape &lt;candidate&gt; safely"):
                self.assertIn(expected, html)
            self.assertNotIn("Escape <candidate>", html)
            for forbidden in ("FAILED_ATTEMPT_SENTINEL", "WORKSPACE_SENTINEL", "GOLD_SENTINEL"):
                self.assertNotIn(forbidden, html)

    def test_experiment_tokens_are_unique(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-results-") as temporary:
            bench = self.build_fixture(Path(temporary))
            experiments = sdd_results.discover(bench)
            tokens = [sdd_results.experiment_token(item) for item in experiments]
            self.assertEqual(len(set(tokens)), len(experiments))

    def test_task_id_that_cannot_form_an_id_gets_no_card(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-results-") as temporary:
            bench = self.build_fixture(Path(temporary))
            config_path = bench / "batch/pilot/fixture.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["tasks"].append(
                {"task_id": "../../escaped", "methods": [{"method": "openspec", "detect": {"run_id": "d"}}]}
            )
            write_json(config_path, config)
            experiments = sdd_results.discover(bench)
            self.assertEqual(
                [item.experiment_id for item in experiments],
                ["fixture-batch-v1", "fixture-batch-v1/owner__repo__pr42"],
            )
            for item in experiments:
                self.assertNotIn("escaped", item.experiment_id)
            # The malformed task stays visible on the flat overview rather than
            # vanishing along with its card.
            targets = sdd_results.batch_targets(overview(experiments), bench)
            self.assertIn("../../escaped", {item.task_id for item in targets})


class SddResultsProductionTests(unittest.TestCase):
    def test_completed_three_pr_batch_is_discoverable(self) -> None:
        experiments = sdd_results.discover(BENCH)
        experiment = sdd_results.resolve(experiments, "scrapy-3pr-both-pilot-v1")
        self.assertEqual(experiment.source_kind, "batch")
        targets = sdd_results.batch_targets(experiment, BENCH)
        self.assertEqual(len({item.task_id for item in targets}), 3)
        self.assertEqual(sum(item.stage == "detect" for item in targets), 9)
        self.assertEqual(sum(item.stage == "update" for item in targets), 18)
        self.assertTrue(all(item.execution is not None for item in targets))

    def test_list_includes_batch_type(self) -> None:
        experiments = sdd_results.discover(BENCH)
        output = io.StringIO()
        with redirect_stdout(output):
            sdd_results.print_list(experiments, BENCH)
        value = output.getvalue()
        self.assertIn("scrapy-3pr-both-pilot-v1", value)
        self.assertIn("batch", value)

    def test_three_pr_batch_splits_into_a_view_per_pr(self) -> None:
        experiments = sdd_results.discover(BENCH)
        group = [item for item in experiments if item.batch_id == "scrapy-3pr-both-pilot-v1"]
        self.assertEqual(len(group), 4)
        self.assertIsNone(overview(group).task_id_filter)
        children = [item for item in group if item.task_id_filter]
        self.assertEqual(
            sorted(item.experiment_id for item in children),
            [
                "scrapy-3pr-both-pilot-v1/scrapy__scrapy__pr8064",
                "scrapy-3pr-both-pilot-v1/scrapy__scrapy__pr8067",
                "scrapy-3pr-both-pilot-v1/scrapy__scrapy__pr8073",
            ],
        )
        for child in children:
            targets = sdd_results.batch_targets(child, BENCH)
            self.assertEqual(len(targets), 9)
            self.assertEqual(sum(item.stage == "detect" for item in targets), 3)
            self.assertEqual(sum(item.stage == "update" for item in targets), 6)
            self.assertTrue(all(item.execution is not None for item in targets))
            self.assertEqual(sdd_results.overall_status(child, BENCH), "SEALED")
            html = sdd_results.build_html(child, BENCH)
            self.assertEqual(html.count('class="tab-button'), 4)
            self.assertIn('data-tab="cc-sdd"', html)

    def test_incomplete_batch_per_pr_view_renders(self) -> None:
        experiments = sdd_results.discover(BENCH)
        child = next(item for item in experiments if item.task_id_filter and item.batch_id == "pr8073-pilot-v1")
        self.assertEqual(sdd_results.overall_status(child, BENCH), "INCOMPLETE")
        html = sdd_results.build_html(child, BENCH)
        self.assertIn('data-tab="overview"', html)

    def test_discovered_tokens_are_unique_production(self) -> None:
        experiments = sdd_results.discover(BENCH)
        tokens = [sdd_results.experiment_token(item) for item in experiments]
        self.assertEqual(len(set(tokens)), len(experiments))


if __name__ == "__main__":
    unittest.main()
