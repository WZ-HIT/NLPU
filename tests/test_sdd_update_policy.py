from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch.core import BatchError
from batch.update_policy import select_update_policy


class UpdatePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix=".update-policy-", dir=ROOT)
        self.task = Path(self.temporary.name) / "scrapy__scrapy__pr8073"
        self.task.mkdir()
        (self.task / "task.json").write_text(
            json.dumps({"baseline": {"base_sha": "1" * 40}}) + "\n", encoding="utf-8"
        )
        (self.task / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        self.schema = json.loads((BENCH / "schemas/update-policy-v1.schema.json").read_text())
        self.validator = Draft202012Validator(self.schema)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _select(self, mode: str, run_id: str) -> dict:
        result = select_update_policy(
            task=self.task,
            bench=BENCH,
            repository_root=ROOT,
            method="openspec",
            mode=mode,
            run_id=run_id,
        )
        return json.loads((ROOT / result["policy"]).read_text())

    def test_sealed_detect_exposes_only_own_sealed_inputs(self) -> None:
        policy = self._select("sealed-detect", "sealed-001")
        self.assertFalse(list(self.validator.iter_errors(policy)))
        self.assertTrue(policy["visibility"]["sealed_detection_manifest"])
        self.assertEqual(policy["base_sha"], "1" * 40)
        self.assertTrue(policy["visibility"]["sealed_planning_artifacts"])
        self.assertFalse(policy["visibility"]["detect_workspace"])
        self.assertEqual(policy["enforcement"]["post_run_diff_rule"], "subset-of-sealed-candidates")
        self.assertIsNone(policy["compose"]["override_path"])

    def test_self_directed_removes_all_detect_inputs(self) -> None:
        policy = self._select("self-directed", "self-001")
        self.assertFalse(list(self.validator.iter_errors(policy)))
        self.assertFalse(policy["visibility"]["sealed_detection_manifest"])
        self.assertFalse(policy["visibility"]["sealed_planning_artifacts"])
        self.assertEqual(policy["enforcement"]["post_run_diff_rule"], "adapter-tests-only")
        override = (ROOT / policy["compose"]["override_path"]).read_text()
        self.assertIn("volumes: !override", override)
        self.assertNotIn("detection-manifest", override)
        self.assertNotIn("sealed-input", override)
        self.assertNotIn("planning-artifacts", override)
        self.assertIn("target: /workspace/tests", override)
        sidecar = (
            self.task / "runs/openspec/update/policies/self-001/update-policy.sha256"
        ).read_text()
        self.assertIn("update-policy.json", sidecar)

    def test_policy_is_immutable(self) -> None:
        self._select("sealed-detect", "immutable-001")
        with self.assertRaises(BatchError) as caught:
            self._select("sealed-detect", "immutable-001")
        self.assertEqual(caught.exception.code, "UPDATE_POLICY_ALREADY_EXISTS")

    def test_schema_rejects_unknown_mode_field_sha_and_path_escape(self) -> None:
        valid = self._select("self-directed", "negative-001")
        cases = []
        value = copy.deepcopy(valid)
        del value["task_id"]
        cases.append(value)
        value = copy.deepcopy(valid)
        value["gold_target_files"] = ["tests/secret.py"]
        cases.append(value)
        value = copy.deepcopy(valid)
        value["mode"] = "automatic"
        cases.append(value)
        value = copy.deepcopy(valid)
        value["compose"]["override_path"] = "../escape.yaml"
        cases.append(value)
        value = copy.deepcopy(valid)
        value["policy_sha256"] = "bad"
        cases.append(value)
        for index, case in enumerate(cases):
            self.assertTrue(list(self.validator.iter_errors(case)), index)


if __name__ == "__main__":
    unittest.main()
