"""The expansion round covers 30 new PRs without rerunning the prior 30."""

import json
import unittest
from pathlib import Path

from batch.rounds import compile_round


BENCH = Path(__file__).resolve().parents[2]
NEW_CONFIG = BENCH / "batch/experiments/scrapy-next30-detect-v1.json"
OLD_CONFIG = BENCH / "batch/experiments/scrapy-30pr-detect-rerun-v1.json"


class Next30RoundTest(unittest.TestCase):
    def test_new_round_has_90_unique_detect_targets_and_no_old_prs(self):
        new = json.loads(NEW_CONFIG.read_text())
        old = json.loads(OLD_CONFIG.read_text())
        self.assertEqual(len(new["prs"]), 30)
        self.assertEqual(len(set(new["prs"])), 30)
        self.assertFalse(set(new["prs"]) & set(old["prs"]))
        first = compile_round(NEW_CONFIG, "next30-001")
        second = compile_round(NEW_CONFIG, "next30-001")
        self.assertEqual(first["prepared_id"], second["prepared_id"])
        self.assertEqual(first["targets"], second["targets"])
        self.assertEqual(len(first["targets"]), 90)
        keys = {(t["task_id"], t["method"], t["stage"], t["mode"], t["run_id"]) for t in first["targets"]}
        self.assertEqual(len(keys), 90)
        self.assertEqual({t["stage"] for t in first["targets"]}, {"detect"})


if __name__ == "__main__":
    unittest.main()
