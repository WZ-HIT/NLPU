from __future__ import annotations

import copy
import json
import shutil
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
from batch.pilot_cli import run
from batch.reporting import Evidence, ReportingError, _publish


class Prompt9PublicationTests(unittest.TestCase):
    def _documents(self) -> dict[str, dict]:
        return {
            "report.json": {"kind": "report", "value": 1},
            "audit.json": {"kind": "audit", "value": 2},
            "evidence-manifest.json": {"kind": "manifest", "value": 3},
        }

    def test_atomic_publication_is_exact_match_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-prompt9-publish-") as temporary:
            final = Path(temporary) / "final"
            documents = self._documents()
            self.assertEqual(_publish(final, documents), "PUBLISHED")
            before = {path.name: path.read_bytes() for path in final.iterdir()}
            self.assertEqual(_publish(final, documents), "EXACT_MATCH")
            self.assertEqual(before, {path.name: path.read_bytes() for path in final.iterdir()})

    def test_publication_refuses_any_existing_difference(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-prompt9-publish-") as temporary:
            final = Path(temporary) / "final"
            documents = self._documents()
            _publish(final, documents)
            changed = copy.deepcopy(documents)
            changed["report.json"]["value"] = 99
            with self.assertRaises(ReportingError) as caught:
                _publish(final, changed)
            self.assertEqual(caught.exception.code, "FINAL_OUTPUT_MISMATCH")


class Prompt9EvidenceBoundaryTests(unittest.TestCase):
    def test_gold_and_workspace_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-prompt9-boundary-") as temporary:
            root = Path(temporary)
            gold = root / "batch/gold/task/result.json"
            workspace = root / "runs/task/workspace/file.json"
            gold.parent.mkdir(parents=True)
            workspace.parent.mkdir(parents=True)
            gold.write_text("{}\n", encoding="utf-8")
            workspace.write_text("{}\n", encoding="utf-8")
            evidence = Evidence(root)
            with self.assertRaises(ReportingError) as gold_error:
                evidence.add(gold)
            self.assertEqual(gold_error.exception.code, "GOLD_PATH_FORBIDDEN")
            with self.assertRaises(ReportingError) as workspace_error:
                evidence.add(workspace)
            self.assertEqual(workspace_error.exception.code, "WORKSPACE_PATH_FORBIDDEN")


class Prompt9CliTests(unittest.TestCase):
    def test_report_rejects_execution_controls_without_dispatch(self) -> None:
        with patch("batch.pilot_cli.generate_final_evidence") as report, patch(
            "batch.pilot_cli.orchestrate"
        ) as orchestrate:
            code = run(["report", "--config", "unused.json", "--resume"])
        self.assertEqual(code, 4)
        report.assert_not_called()
        orchestrate.assert_not_called()

    def test_report_dispatches_directly_without_orchestrator(self) -> None:
        result = {
            "schema_version": 1,
            "batch_id": "unit",
            "status": "READY",
            "audit_status": "PASS_WITH_LIMITATIONS",
        }
        with patch("batch.pilot_cli.generate_final_evidence", return_value=result) as report, patch(
            "batch.pilot_cli.orchestrate"
        ) as orchestrate:
            code = run(["report", "--config", "unused.json"])
        self.assertEqual(code, 0)
        report.assert_called_once()
        orchestrate.assert_not_called()


class Prompt9ProductionPackageTests(unittest.TestCase):
    FINAL = BENCH / "batch/runs/scrapy-3pr-both-pilot-v1/final"

    def test_final_package_validates_and_records_operational_facts(self) -> None:
        documents = {}
        for document, schema in (
            ("report.json", "batch-final-report-v1.schema.json"),
            ("audit.json", "batch-final-audit-v1.schema.json"),
            ("evidence-manifest.json", "batch-evidence-manifest-v1.schema.json"),
        ):
            value = json.loads((self.FINAL / document).read_text(encoding="utf-8"))
            schema_value = json.loads((BENCH / "schemas" / schema).read_text(encoding="utf-8"))
            Draft202012Validator(schema_value).validate(value)
            documents[document] = value
        report = documents["report.json"]
        self.assertEqual(report["status"], "PASS_WITH_LIMITATIONS")
        self.assertEqual(report["counts"]["detect_sealed"], 9)
        self.assertEqual(report["counts"]["update_sealed"], 18)
        self.assertEqual(report["counts"]["historical_failed_events"], 16)
        self.assertEqual(report["counts"]["final_scope_violations"], 0)
        self.assertFalse(report["semantics"]["project_tests_run"])
        self.assertFalse(report["semantics"]["evaluation_dispatched"])
        payload = dict(report)
        supplied = payload.pop("report_sha256")
        self.assertEqual(supplied, canonical_sha256(payload))

    def test_evidence_manifest_commits_to_report_and_audit(self) -> None:
        manifest = json.loads((self.FINAL / "evidence-manifest.json").read_text(encoding="utf-8"))
        payload = dict(manifest)
        supplied = payload.pop("manifest_sha256")
        self.assertEqual(supplied, canonical_sha256(payload))
        self.assertEqual(manifest["output_file_count"], 2)
        self.assertEqual(
            [Path(item["path"]).name for item in manifest["output_files"]],
            ["report.json", "audit.json"],
        )


if __name__ == "__main__":
    unittest.main()
