from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
TASK = BENCH / "tasks/scrapy__scrapy__pr8073"
METHODS = ("openspec", "speckit", "cc-sdd")


class ComposePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((BENCH / "schemas/preflight-v1.schema.json").read_text())
        cls.validator = Draft202012Validator(cls.schema)
        cls.reports = {
            (method, stage): json.loads(
                (TASK / "runs" / method / stage / "preflight/preflight-report.json").read_text()
            )
            for method in METHODS
            for stage in ("detect", "update")
        }

    def test_all_six_reports_validate(self) -> None:
        for key, report in self.reports.items():
            self.assertFalse(list(self.validator.iter_errors(report)), key)
            self.assertFalse(report["formal_prompt_sent"])
            self.assertFalse(report["model_request_sent"])
            self.assertFalse(report["project_tests_run"])

    def test_schema_fails_closed(self) -> None:
        valid = self.reports[("openspec", "detect")]
        cases = []
        item = copy.deepcopy(valid)
        del item["method"]
        cases.append(item)
        item = copy.deepcopy(valid)
        item["unknown_field"] = True
        cases.append(item)
        item = copy.deepcopy(valid)
        item["compose"]["rendered_path"] = "../escape.yaml"
        cases.append(item)
        item = copy.deepcopy(valid)
        item["images"]["agent_image_id"] = "not-a-sha"
        cases.append(item)
        for index, case in enumerate(cases):
            self.assertTrue(list(self.validator.iter_errors(case)), index)

    def test_detect_ready_update_waits_for_real_seal(self) -> None:
        for method in METHODS:
            detect = self.reports[(method, "detect")]
            update = self.reports[(method, "update")]
            self.assertEqual(detect["status"], "READY")
            self.assertTrue(detect["formal_run_permitted"])
            self.assertEqual(update["status"], "BLOCKED")
            self.assertFalse(update["formal_run_permitted"])
            self.assertEqual(update["blockers"], ["formal_detection_seal_missing"])

    def test_permissions_match_stage_policy(self) -> None:
        detect = {
            "scrapy_write": "DENIED", "tests_write": "DENIED",
            "planning_write": "ALLOWED", "output_write": "ALLOWED",
            "sealed_input_write": "NOT_APPLICABLE",
        }
        update = {
            "scrapy_write": "DENIED", "tests_write": "ALLOWED",
            "planning_write": "DENIED", "output_write": "ALLOWED",
            "sealed_input_write": "DENIED",
        }
        for method in METHODS:
            self.assertEqual(self.reports[(method, "detect")]["permissions"], detect)
            self.assertEqual(self.reports[(method, "update")]["permissions"], update)

    def test_rendered_hashes_match_deployment_lock(self) -> None:
        lock = json.loads((TASK / "compose-deployment-lock.json").read_text())
        self.assertEqual(len(lock["rendered"]), 6)
        for record in lock["rendered"]:
            path = ROOT / record["rendered_path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record["rendered_sha256"])

    def test_compose_has_no_forbidden_host_mounts(self) -> None:
        text = (TASK / "compose.yaml").read_text()
        for token in ("output/raw_prs", "batch/inventories", "/var/run/docker.sock", "host-gold"):
            self.assertNotIn(token, text)
        compose = yaml.safe_load(text)
        self.assertEqual(len(compose["services"]), 12)
        for service in compose["services"].values():
            self.assertTrue(service["read_only"])
            self.assertEqual(service["cap_drop"], ["ALL"])


if __name__ == "__main__":
    unittest.main()
