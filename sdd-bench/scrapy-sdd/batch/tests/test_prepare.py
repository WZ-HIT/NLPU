"""Prepared manifest contract and historical target compatibility."""

import json
import tempfile
import unittest
from pathlib import Path

from batch.core import BatchError
from batch.prepare import ROOT, compile_experiment

BENCH = Path(__file__).resolve().parents[2]
EXAMPLES = BENCH / "batch/experiments"
BASELINE = json.loads((BENCH / "docs/refactor/baseline.json").read_text(encoding="utf-8"))


def identity(target):
    return (target["task_id"], target["method"], target["stage"], target["mode"], target["run_id"])


class PrepareTests(unittest.TestCase):
    def compile_modified(self, name, change):
        source = EXAMPLES / f"{name}.json"
        config = json.loads(source.read_text(encoding="utf-8"))
        change(config)
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            return compile_experiment(path)

    def test_examples_match_p0_and_repeat_byte_for_byte(self):
        for batch in BASELINE["batches"]:
            with self.subTest(batch=batch["batch_id"]):
                path = EXAMPLES / f"{batch['batch_id']}.json"
                first = compile_experiment(path)
                second = compile_experiment(path)
                self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
                self.assertEqual(first["target_count"], batch["target_count"])
                self.assertEqual({identity(t) for t in first["targets"]}, {identity(t) for t in batch["targets"]})
                self.assertEqual(len({t["target_id"] for t in first["targets"]}), first["target_count"])
                self.assertEqual({t["base_sha"] for t in first["targets"]}, {t["base_sha"] for t in batch["targets"]})

    def test_duplicate_pr(self):
        with self.assertRaises(BatchError) as caught:
            self.compile_modified("scrapy-3pr-both-pilot-v1", lambda c: c["prs"].append(c["prs"][0]))
        self.assertEqual(caught.exception.code, "PREPARE_DUPLICATE_PR")

    def test_illegal_method(self):
        with self.assertRaises(BatchError) as caught:
            self.compile_modified("scrapy-3pr-both-pilot-v1", lambda c: c["methods"].append("unknown"))
        self.assertEqual(caught.exception.code, "PREPARE_SCHEMA_INVALID")

    def test_update_without_detect(self):
        with self.assertRaises(BatchError) as caught:
            self.compile_modified("scrapy-3pr-both-pilot-v1", lambda c: c.update(stages=["update"]))
        self.assertEqual(caught.exception.code, "PREPARE_SCHEMA_INVALID")

    def test_stale_source_input(self):
        with self.assertRaises(BatchError) as caught:
            self.compile_modified("scrapy-3pr-both-pilot-v1", lambda c: c["source_batch"].update(sha256="0" * 64))
        self.assertEqual(caught.exception.code, "PREPARE_INPUT_STALE")

    def test_stale_evaluation_input(self):
        with self.assertRaises(BatchError) as caught:
            self.compile_modified("scrapy-3pr-both-pilot-v1", lambda c: c["evaluation"]["plan"].update(sha256="0" * 64))
        self.assertEqual(caught.exception.code, "PREPARE_INPUT_STALE")


if __name__ == "__main__":
    unittest.main()
