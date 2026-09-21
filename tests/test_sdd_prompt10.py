from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch.core import BatchError, canonical_sha256
from batch.evaluator import (
    METRIC_VERSION,
    _opaque_id,
    _publish_tree,
    aggregate_rows,
    choose_attribution,
    score_ranked,
)
from batch.pilot_cli import run


class Prompt10MetricTests(unittest.TestCase):
    def test_set_and_ranking_metrics_preserve_order_and_accounting(self) -> None:
        value = score_ranked(
            ["tests/extra.py", "tests/gold.py", "tests/other.py"],
            ["tests/gold.py", "tests/missing.py"],
            invalid_count=2,
            missing_count=1,
        )
        self.assertEqual(value["metric_definition_version"], METRIC_VERSION)
        self.assertEqual((value["tp"], value["fp"], value["fn"]), (1, 2, 1))
        self.assertEqual(value["precision"], 1 / 3)
        self.assertEqual(value["recall"], 1 / 2)
        self.assertEqual(value["f1"], 0.4)
        self.assertEqual(value["hit_at_1"], 0)
        self.assertEqual(value["hit_at_3"], 1)
        self.assertEqual(value["recall_at_3"], 0.5)
        self.assertEqual(value["mrr"], 0.5)
        self.assertEqual(value["invalid_count"], 2)
        self.assertEqual(value["missing_count"], 1)

    def test_symbol_identity_is_path_qualified(self) -> None:
        value = score_ranked(
            [{"path": "tests/a.py", "qualified_name": "Suite.test_x"}],
            [{"path": "tests/b.py", "qualified_name": "Suite.test_x"}],
        )
        self.assertEqual(value["tp"], 0)
        self.assertEqual(value["fp"], 1)
        self.assertEqual(value["fn"], 1)

    def test_empty_prediction_does_not_divide_by_zero(self) -> None:
        value = score_ranked([], ["tests/gold.py"], missing_count=1)
        self.assertEqual(value["precision"], 0.0)
        self.assertEqual(value["recall"], 0.0)
        self.assertIsNone(value["gold_to_predicted_ratio"])

    def test_attribution_precedence_is_deterministic(self) -> None:
        self.assertEqual(
            choose_attribution(
                {
                    "functional_failure": True,
                    "patch_application_failure": True,
                    "policy_violation": True,
                    "invalid_evidence": True,
                }
            ),
            "invalid_evidence",
        )
        self.assertEqual(choose_attribution({}), "success")

    def test_opaque_ids_are_deterministic_and_domain_separated(self) -> None:
        first = _opaque_id("evaluation", "file", "tests/test_x.py")
        self.assertEqual(first, _opaque_id("evaluation", "file", "tests/test_x.py"))
        self.assertNotEqual(first, _opaque_id("evaluation", "symbol", "tests/test_x.py"))
        self.assertNotIn("test_x", first)


class Prompt10AggregationTests(unittest.TestCase):
    def _row(self, task: str, classification: str, method: str, mode: str, tp: int, fp: int, fn: int) -> dict:
        denominator = tp + fp
        precision = tp / denominator if denominator else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metric = {
            "metric_definition_version": METRIC_VERSION,
            "gold_count": tp + fn,
            "predicted_count": tp + fp,
            "matched_count": tp,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "exact_match": int(fp == fn == 0),
            "any_hit": int(tp > 0),
            "all_hit": int(fn == 0),
            "hit_at_1": int(tp > 0),
            "recall_at_1": recall,
            "hit_at_3": int(tp > 0),
            "recall_at_3": recall,
            "hit_at_5": int(tp > 0),
            "recall_at_5": recall,
            "mrr": float(tp > 0),
            "gold_to_predicted_ratio": (tp + fn) / denominator if denominator else None,
            "invalid_count": 0,
            "missing_count": fn,
            "scorable_count": tp + fn,
        }
        return {
            "stage": "update",
            "task_id": task,
            "classification": classification,
            "method": method,
            "update_mode": mode,
            "validity": {"status": "VALID"},
            "model_performance": {"file": metric, "symbol": copy.deepcopy(metric)},
        }

    def test_macro_and_micro_are_distinct_and_fully_stratified(self) -> None:
        rows = [
            self._row("a", "TEST_ONLY_PR", "openspec", "sealed-detect", 1, 0, 0),
            self._row("b", "MIXED_CODE_AND_TEST_PR", "openspec", "sealed-detect", 1, 9, 0),
        ]
        output = aggregate_rows(rows, "update")
        overall = next(row for row in output if row["classification"] == "ALL" and row["dimensions"] == {})
        self.assertEqual(overall["file"]["macro"]["precision"], 0.55)
        self.assertEqual(overall["file"]["micro"]["precision"], 2 / 11)
        self.assertTrue(any(row["dimensions"] == {"method": "openspec", "update_mode": "sealed-detect"} for row in output))
        for row in output:
            self.assertIn("invalid_count", row["file"])
            self.assertIn("missing_count", row["file"])
            self.assertEqual(row["file"]["metric_definition_version"], METRIC_VERSION)


class Prompt10PublicationTests(unittest.TestCase):
    def test_atomic_tree_is_exact_match_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-prompt10-publish-") as temporary:
            destination = Path(temporary) / "evaluation"
            files = {"a.json": b"{}\n", "runs/one/log.txt": b"ok\n"}
            self.assertEqual(_publish_tree(destination, files), "PUBLISHED")
            self.assertEqual(_publish_tree(destination, files), "EXACT_MATCH")
            with self.assertRaises(BatchError) as caught:
                _publish_tree(destination, {**files, "a.json": b'{"changed":true}\n'})
            self.assertEqual(caught.exception.code, "EVALUATION_OUTPUT_MISMATCH")


class Prompt10ContractAndCliTests(unittest.TestCase):
    def test_plan_and_new_schemas_are_valid_draft_2020_12(self) -> None:
        plan = json.loads((BENCH / "batch/evaluation-plans/scrapy-3pr-prompt10-v1.json").read_text(encoding="utf-8"))
        schema = json.loads((BENCH / "schemas/host-evaluation-plan-v1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(plan)
        self.assertEqual(plan["metric_definition_version"], METRIC_VERSION)
        self.assertEqual(plan["gates"]["sealed_target_count"], 27)
        plan_v2_schema = json.loads((BENCH / "schemas/host-evaluation-plan-v2.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(plan_v2_schema)
        plan_v2 = copy.deepcopy(plan)
        plan_v2["schema_version"] = 2
        plan_v2["gates"]["sealed_target_count"] = 60
        Draft202012Validator(plan_v2_schema).validate(plan_v2)
        for name in (
            "host-gold-store-v1.schema.json",
            "host-target-set-v1.schema.json",
            "host-run-evaluation-v1.schema.json",
            "host-evaluation-manifest-v1.schema.json",
        ):
            Draft202012Validator.check_schema(json.loads((BENCH / "schemas" / name).read_text(encoding="utf-8")))

    def test_evaluate_host_dispatches_without_orchestrator(self) -> None:
        result = {"schema_version": 1, "status": "READY", "evaluation_id": "unit"}
        with patch("batch.pilot_cli.evaluate_host", return_value=result) as evaluate, patch(
            "batch.pilot_cli.orchestrate"
        ) as orchestrate:
            code = run(["evaluate-host", "--config", "unused.json"])
        self.assertEqual(code, 0)
        evaluate.assert_called_once()
        orchestrate.assert_not_called()

    def test_evaluate_host_accepts_prepared_manifest(self) -> None:
        result = {"schema_version": 1, "status": "READY", "evaluation_id": "unit"}
        with patch("batch.pilot_cli.evaluate_host", return_value=result) as evaluate, patch(
            "batch.pilot_cli.orchestrate"
        ) as orchestrate:
            code = run(["evaluate-host", "--manifest", "prepared.json"])
        self.assertEqual(code, 0)
        self.assertIsNone(evaluate.call_args.kwargs["config_path"])
        self.assertEqual(evaluate.call_args.kwargs["manifest_path"], Path("prepared.json").resolve())
        orchestrate.assert_not_called()

    def test_evaluate_host_rejects_execution_controls(self) -> None:
        with patch("batch.pilot_cli.evaluate_host") as evaluate, patch(
            "batch.pilot_cli.orchestrate"
        ) as orchestrate:
            code = run(["evaluate-host", "--config", "unused.json", "--resume"])
        self.assertEqual(code, 4)
        evaluate.assert_not_called()
        orchestrate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
