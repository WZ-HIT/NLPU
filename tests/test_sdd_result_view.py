from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch.core import canonical_sha256, sha256_file
from batch.orchestrator import target_key, validate_prepared_manifest
from batch.result_view import build, load


class HistoricalResultViewTests(unittest.TestCase):
    def view(self, batch_id: str) -> dict:
        path = BENCH / "batch/runs" / batch_id / "result-view.json"
        return load(path, BENCH, ROOT)

    def test_complete_dual_mode_view_matches_p0(self) -> None:
        value = self.view("scrapy-3pr-both-pilot-v1")
        self.assertEqual(value["counts"]["target_count"], 27)
        self.assertEqual(value["counts"]["detect_count"], 9)
        self.assertEqual(value["counts"]["update_count"], 18)
        self.assertEqual(value["counts"]["terminal_count"], 27)
        self.assertEqual(len(value["targets"]), len(set(value["targets"])))
        self.assertEqual(len({row["target_id"] for row in value["targets"].values()}), 27)
        self.assertTrue(all(row["seal"] for row in value["targets"].values()))

    def test_p2_targets_map_uniquely_to_p3_ledger_keys(self) -> None:
        manifest = BENCH / "docs/refactor/simulation-3pr/prepared-manifest.json"
        config, targets = validate_prepared_manifest(manifest, BENCH, ROOT)
        keys = [target_key(target) for target in targets]
        ids = [target["target_id"] for target in targets]
        self.assertEqual((len(targets), len(set(keys)), len(set(ids))), (27, 27, 27))
        self.assertEqual(config["evaluation"]["kind"], "host-plan")
        self.assertEqual(
            config["source_batch"]["path"],
            "sdd-bench/scrapy-sdd/batch/pilot/scrapy-3pr-both-pilot-v1.json",
        )

    def test_detect_only_partial_failure_view_matches_p0(self) -> None:
        value = self.view("scrapy-20pr-detect-v1")
        self.assertEqual(value["counts"]["target_count"], 60)
        self.assertEqual(value["counts"]["detect_count"], 60)
        self.assertEqual(value["counts"]["update_count"], 0)
        self.assertEqual(value["counts"]["terminal_count"], 55)
        self.assertEqual(value["counts"]["states"], {"DETECT_SEALED": 55, "FAILED": 5})

    def test_view_is_gold_free_and_references_seals_without_mutating_them(self) -> None:
        path = BENCH / "batch/runs/scrapy-3pr-both-pilot-v1/result-view.json"
        before = {
            row["seal"]["path"]: sha256_file(ROOT / row["seal"]["path"])
            for row in self.view("scrapy-3pr-both-pilot-v1")["targets"].values()
        }
        rebuilt = build(BENCH / "batch/pilot/scrapy-3pr-both-pilot-v1.json", BENCH, ROOT)
        self.assertEqual(rebuilt, json.loads(path.read_text(encoding="utf-8")))
        self.assertNotIn("gold", json.dumps(rebuilt).lower())
        self.assertEqual(
            before,
            {name: sha256_file(ROOT / name) for name in before},
        )
        payload = dict(rebuilt)
        self.assertEqual(payload.pop("view_sha256"), canonical_sha256(payload))


if __name__ == "__main__":
    unittest.main()
