"""Unified CLI acceptance with a fake Agent and the real P3 ledger coordinator."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from batch import experiment_cli
from batch.orchestrator import target_key

REPO = Path(__file__).resolve().parents[4]
REAL_BENCH = REPO / "sdd-bench/scrapy-sdd"


class ExperimentCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=REPO)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bench = self.root / "sdd-bench/scrapy-sdd"
        (self.bench / "schemas").mkdir(parents=True)
        (self.bench / "schemas/batch-ledger-event-v1.schema.json").write_bytes(
            (REAL_BENCH / "schemas/batch-ledger-event-v1.schema.json").read_bytes()
        )
        task = self.bench / "tasks/task-pr1/task.json"
        task.parent.mkdir(parents=True)
        task.write_text(json.dumps({"task_id": "task-pr1"}), encoding="utf-8")
        policy = task.parent / "policy.json"
        policy.write_text("{}", encoding="utf-8")
        self.targets = [
            {"target_id": "target-detect", "task_id": "task-pr1", "task_manifest": task,
             "method": "openspec", "stage": "detect", "run_id": "detect-001", "mode": None,
             "policy": None, "policy_sha256": None},
            {"target_id": "target-update", "task_id": "task-pr1", "task_manifest": task,
             "method": "openspec", "stage": "update", "run_id": "update-001", "mode": "sealed-detect",
             "policy": policy, "policy_sha256": "a" * 64},
        ]
        self.prepared = {"prepared_id": "prepared-" + "1" * 24, "experiment_id": "fake",
                         "target_count": 2, "inputs": {"evaluation": {"kind": "host-plan", "plan": {"path": "plan.json"}}}}
        directory = self.bench / "batch/prepared/fake"
        directory.mkdir(parents=True)
        self.manifest = directory / "prepared-manifest.json"
        self.manifest.write_text(json.dumps(self.prepared), encoding="utf-8")
        self.config = self.root / "experiment.json"
        self.config.write_text("{}", encoding="utf-8")
        self.run_config = {"batch_id": self.prepared["prepared_id"], "prepared_id": self.prepared["prepared_id"],
                           "experiment_id": "fake"}

    def invoke(self, *argv: str) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = experiment_cli.run(list(argv))
        return code, json.loads(output.getvalue())

    def test_prepare_detect_update_evaluate_with_fake_agent(self) -> None:
        calls: list[str] = []
        def fake_detect(**kwargs):
            calls.append("detect")
            return {"status": "SEALED"}
        def fake_update(**kwargs):
            calls.append("update")
            self.assertEqual(kwargs["policy_path"], self.targets[1]["policy"])
            return {"status": "SEALED"}
        def barrier(**kwargs):
            calls.append("barrier")
            self.assertEqual(kwargs["latest"][target_key(self.targets[0])]["state"], "DETECT_SEALED")
            return {"barrier_sha256": "b" * 64}
        with patch.object(experiment_cli, "BENCH", self.bench), \
             patch.object(experiment_cli, "ROOT", self.root), \
             patch.object(experiment_cli, "_compiled", return_value=self.prepared), \
             patch.object(experiment_cli, "prepare", return_value=self.prepared), \
             patch.object(experiment_cli, "load_prepared", return_value=self.prepared), \
             patch.object(experiment_cli, "write_result_view", return_value=({"view_sha256": "c" * 64}, self.bench / "batch/runs/view.json")) as write_view, \
             patch("batch.orchestrator.validate_prepared_manifest", return_value=(self.run_config, self.targets)), \
             patch("batch.orchestrator.detect_targets", side_effect=fake_detect), \
             patch("batch.orchestrator.update_tests", side_effect=fake_update), \
             patch("batch.orchestrator._ensure_detect_barrier", side_effect=barrier), \
             patch.object(experiment_cli, "generate_final_evidence", return_value={"status": "READY"}) as compliance, \
             patch.object(experiment_cli, "evaluate_host", return_value={"status": "READY"}) as quality:
            code, value = self.invoke("prepare", str(self.config))
            self.assertEqual((code, value["status"], value["target_count"]), (0, "FROZEN", 2))
            code, value = self.invoke("run", str(self.config), "--stage", "detect")
            self.assertEqual((code, value["error"]["code"]), (4, "EXPERIMENT_EXECUTE_REQUIRED"))
            code, value = self.invoke("run", str(self.config), "--stage", "detect", "--execute", "--no-archive")
            self.assertEqual((code, value["status"], value["results"][0]["state"]), (0, "READY", "DETECT_SEALED"))
            code, value = self.invoke("run", str(self.config), "--stage", "update", "--execute", "--no-archive")
            self.assertEqual((code, value["status"], value["results"][0]["state"]), (0, "READY", "UPDATE_SEALED"))
            code, value = self.invoke("evaluate", str(self.config), "--kind", "both")
            self.assertEqual((code, value["status"]), (0, "READY"))
            compliance.assert_called_once()
            quality.assert_called_once()
            self.assertEqual(write_view.call_count, 2)
        self.assertEqual(calls, ["detect", "barrier", "barrier", "update"])
        ledger = self.bench / "batch/runs" / self.prepared["prepared_id"] / "ledger.jsonl"
        self.assertTrue(ledger.is_file())

    def test_result_report_resolves_prepared_id_from_config(self) -> None:
        viewer = Mock()
        viewer.main.return_value = 0
        with patch.object(experiment_cli, "BENCH", self.bench), \
             patch.object(experiment_cli, "ROOT", self.root), \
             patch.object(experiment_cli, "_compiled", return_value=self.prepared), \
             patch.object(experiment_cli, "load_prepared", return_value=self.prepared), \
             patch.object(experiment_cli, "viewer_module", return_value=viewer):
            output = io.StringIO()
            with redirect_stdout(output):
                code = experiment_cli.run(["results", "report", "--config", str(self.config)])
        self.assertEqual(code, 0)
        self.assertEqual(viewer.main.call_args.args[0][-2:], ["report", self.prepared["prepared_id"]])

    def test_inspect_is_read_only_and_results_require_config(self) -> None:
        with patch.object(experiment_cli, "BENCH", self.bench), \
             patch.object(experiment_cli, "ROOT", self.root), \
             patch.object(experiment_cli, "_compiled", return_value=self.prepared), \
             patch.object(experiment_cli, "load_prepared", return_value=self.prepared), \
             patch("batch.orchestrator.validate_prepared_manifest", return_value=(self.run_config, self.targets)):
            ledger = self.bench / "batch/runs" / self.prepared["prepared_id"] / "ledger.jsonl"
            code, value = self.invoke("run", str(self.config))
            self.assertEqual((code, value["command"]), (0, "inspect"))
            self.assertFalse(ledger.exists())
            code, value = self.invoke("results", "summary")
            self.assertEqual((code, value["error"]["code"]), (4, "EXPERIMENT_CONFIG_REQUIRED"))


if __name__ == "__main__":
    unittest.main()
