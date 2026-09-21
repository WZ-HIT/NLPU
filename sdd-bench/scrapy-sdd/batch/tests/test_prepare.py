"""Prepared manifest contract and historical target compatibility."""

import json
import tempfile
import unittest
from pathlib import Path

from batch.core import BatchError, sha256_file
from batch.prepare import ROOT, _image_record, compile_experiment

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
                self.assertEqual({row["base_sha"] for row in first["images"]}, {t["base_sha"] for t in first["targets"]})
                for row in first["images"]:
                    self.assertEqual(sha256_file(ROOT / row["deployment_lock"]["path"]), row["deployment_lock"]["sha256"])
                    self.assertEqual(sha256_file(ROOT / row["baseline_lock"]["path"]), row["baseline_lock"]["sha256"])
                    self.assertTrue(row["agent"]["image_id"].startswith("sha256:"))
                self.assertEqual({identity(t) for t in first["targets"]}, {identity(t) for t in batch["targets"]})
                self.assertEqual(len({t["target_id"] for t in first["targets"]}), first["target_count"])
                self.assertEqual({t["base_sha"] for t in first["targets"]}, {t["base_sha"] for t in batch["targets"]})

    def test_image_lock_rejects_stale_baseline_and_invalid_image_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = "a" * 40
            baseline = root / "sdd-bench/scrapy-sdd/batch/baselines" / base / "baseline-lock.json"
            deployment = root / "sdd-bench/scrapy-sdd/batch/images" / base / "deployment-lock.json"
            baseline.parent.mkdir(parents=True)
            deployment.parent.mkdir(parents=True)
            baseline.write_text("{}", encoding="utf-8")
            lock = {
                "status": "READY", "base_sha": base,
                "baseline_lock_sha256": sha256_file(baseline),
                "images": {
                    "agent": {"tag": "agent:test", "image_id": "sha256:" + "b" * 64},
                    "baseline": {"tag": "baseline:test", "image_id": "sha256:" + "c" * 64},
                },
            }
            deployment.write_text(json.dumps(lock), encoding="utf-8")
            self.assertEqual(_image_record(root, base)["agent"]["image_id"], "sha256:" + "b" * 64)
            lock["baseline_lock_sha256"] = "0" * 64
            deployment.write_text(json.dumps(lock), encoding="utf-8")
            with self.assertRaises(BatchError) as stale:
                _image_record(root, base)
            self.assertEqual(stale.exception.code, "PREPARE_IMAGE_LOCK_MISMATCH")
            lock["baseline_lock_sha256"] = sha256_file(baseline)
            lock["images"]["agent"]["image_id"] = "not-a-digest"
            deployment.write_text(json.dumps(lock), encoding="utf-8")
            with self.assertRaises(BatchError) as invalid:
                _image_record(root, base)
            self.assertEqual(invalid.exception.code, "PREPARE_IMAGE_ID_INVALID")

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
