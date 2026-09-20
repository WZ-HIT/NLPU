from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
TASK = BENCH / "tasks/scrapy__scrapy__pr8073"
METHODS = ("openspec", "speckit", "cc-sdd")


class GoldAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.detection_schema = json.loads((BENCH / "schemas/detection-v1.schema.json").read_text())
        cls.gold_schema = json.loads((BENCH / "schemas/gold-check-v1.schema.json").read_text())

    def test_detection_schema_is_fail_closed(self) -> None:
        valid = {
            "schema_version": 1,
            "manifest_type": "SEALED_DETECTION",
            "task_id": "scrapy__scrapy__pr8073",
            "method": "openspec",
            "base_sha": "1" * 40,
            "producer": {"kind": "agent", "stage": "detect", "run_id": "run-1", "session_sha256": "2" * 64},
            "task_input_sha256": "3" * 64,
            "candidates": [{"path": "tests/test_example.py", "symbols": ["test_example"], "reason": "Repository evidence."}],
            "planning_artifacts": {"file_count": 1, "manifest_sha256": "4" * 64},
            "seal": {"algorithm": "sha256-canonical-json-without-seal", "payload_sha256": "5" * 64},
        }
        validator = Draft202012Validator(self.detection_schema)
        self.assertFalse(list(validator.iter_errors(valid)))
        for mutate in ("missing", "unknown", "sha", "path"):
            value = copy.deepcopy(valid)
            if mutate == "missing": del value["task_id"]
            elif mutate == "unknown": value["gold_target"] = "hidden"
            elif mutate == "sha": value["base_sha"] = "not-a-sha"
            else: value["candidates"][0]["path"] = "../escape.py"
            self.assertTrue(list(validator.iter_errors(value)), mutate)

    def test_all_stage_reports_pass_schema_and_checks(self) -> None:
        validator = Draft202012Validator(self.gold_schema)
        for method in METHODS:
            for stage in ("detect", "update"):
                report = json.loads((TASK / "runs" / method / stage / "audit/gold-check-report.json").read_text())
                self.assertFalse(list(validator.iter_errors(report)), (method, stage))
                self.assertEqual(report["status"], "PASS")
                self.assertEqual({x["id"] for x in report["checks"]}, {f"G{i:02d}" for i in range(1, 9)})
                self.assertTrue(all(x["status"] == "PASS" for x in report["checks"]))
                self.assertEqual(report["agent_call_permitted"], stage == "detect")

    def test_evidence_total_changes_for_each_boundary_class(self) -> None:
        audit = TASK / "runs/openspec/update/audit"
        names = ["visible-files.sha256", "prompt-provenance.json", "mount-audit.json", "git-object-audit.json", "isolation-audit.json", "manifest-transfer-audit.json"]
        def total(overrides=None):
            overrides = overrides or {}
            entries = []
            for name in names:
                data = overrides.get(name, (audit / name).read_bytes())
                entries.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
            encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            return hashlib.sha256(encoded).hexdigest()
        original = total()
        for name in ("visible-files.sha256", "mount-audit.json", "manifest-transfer-audit.json"):
            changed = (audit / name).read_bytes() + b"tamper"
            self.assertNotEqual(original, total({name: changed}), name)

    def test_update_probe_sees_only_own_sealed_manifest(self) -> None:
        seals = set()
        for method in METHODS:
            audit = TASK / "runs" / method / "update/audit"
            isolation = json.loads((audit / "isolation-audit.json").read_text())
            transfer = json.loads((audit / "manifest-transfer-audit.json").read_text())
            self.assertEqual(isolation["container_probe"]["other_input_entries"], ["detection-manifest.json"])
            self.assertFalse(isolation["detect_workspace_visible_to_update"])
            self.assertTrue(transfer["same_method_only"])
            self.assertFalse(transfer["other_detection_results_visible"])
            seals.add(transfer["seal_sha256"])
        self.assertEqual(len(seals), 3)


if __name__ == "__main__":
    unittest.main()
