from __future__ import annotations

import copy
import json
import math
import unittest
from unittest.mock import patch

from experiment import bm25_localization as bm
from experiment import tfidf_localization as tf
from tests import test_bm25_localization as fixtures


class TFIDFTests(unittest.TestCase):
    def test_smoothed_idf_raw_tf_and_cosine_match_hand_calculation(self):
        ranker = tf.TFIDFCosine({"a": ["apple", "apple", "banana"],
                                 "b": ["apple", "pear"], "c": ["banana"]})
        idf = math.log(4 / 3) + 1
        pear_idf = math.log(4 / 2) + 1
        self.assertAlmostEqual(ranker.idf["apple"], idf)
        self.assertAlmostEqual(ranker.idf["pear"], pear_idf)
        scores = {entry["id"]: entry["score"] for entry in ranker.rank("apple banana")}
        self.assertAlmostEqual(scores["a"], 3 / math.sqrt(10))
        self.assertAlmostEqual(scores["b"], idf / (math.sqrt(2) * math.sqrt(idf ** 2 + pear_idf ** 2)))
        self.assertAlmostEqual(scores["c"], 1 / math.sqrt(2))

    def test_query_scaling_oov_and_base_only_fitting(self):
        ranker = tf.TFIDFCosine({"a": ["alpha", "beta"], "b": ["beta", "beta"]})
        original = copy.deepcopy(ranker.idf)
        a = ranker.rank("alpha beta")
        b = ranker.rank("alpha alpha beta beta unseen")
        self.assertEqual([item["id"] for item in a], [item["id"] for item in b])
        for x, y in zip(a, b):
            self.assertAlmostEqual(x["score"], y["score"])
        self.assertEqual(ranker.idf, original)
        self.assertNotIn("unseen", ranker.idf)

    def test_document_normalization_zero_vectors_and_tie_order(self):
        ranker = tf.TFIDFCosine({"z": ["alpha"] * 100, "a": ["alpha"], "empty": []})
        ranked = ranker.rank("alpha")
        self.assertEqual([entry["id"] for entry in ranked], ["a", "z", "empty"])
        self.assertAlmostEqual(ranked[0]["score"], 1.0)
        self.assertAlmostEqual(ranked[1]["score"], 1.0)
        for query in ("", "unseen"):
            zero = ranker.rank(query)
            self.assertEqual([entry["id"] for entry in zero], ["a", "empty", "z"])
            self.assertTrue(all(entry["score"] == 0 for entry in zero))

    def test_reused_raw_counts_produce_identical_tfidf_results(self):
        documents = {"a": bm.tokenize("HTTPResponse alpha alpha"), "b": bm.tokenize("alpha beta")}
        counts = bm.BM25(documents)
        a, b = tf.TFIDFCosine(documents), tf.TFIDFCosine.from_counts(counts.ids, counts.postings)
        self.assertEqual(a.idf, b.idf)
        self.assertEqual(a.rank("http alpha"), b.rank("http alpha"))


class TFIDFExperimentTests(unittest.TestCase):
    setUp = fixtures.ExperimentTests.setUp
    save_inputs = fixtures.ExperimentTests.save_inputs

    def run_experiment(self, name="run"):
        return tf.run_experiment(inventory_path=self.inventory, raw_path=self.raw,
                                 bench=self.bench, output=self.root / name)

    def test_run_reuses_protocol_without_bm25_scoring_and_seals_before_gold(self):
        original = tf.build_labels

        def after_seal(raw, index):
            self.assertEqual(len(list((self.root / "run/predictions").glob("*.gz"))), 3)
            self.assertTrue((self.root / "run/predictions-manifest.json").exists())
            return original(raw, index)

        with patch.object(bm.BM25, "rank", side_effect=AssertionError("BM25 scoring forbidden")), \
                patch.object(tf, "build_labels", side_effect=after_seal):
            summary = self.run_experiment()
        self.assertEqual(summary["status_counts"], {"LABELS_INCOMPLETE": 1, "NO_POSITIVE_GOLD": 1, "SCORED": 1})
        self.assertEqual(tf.verify_run(self.root / "run")["status"], "PASS")
        self.assertEqual(len((self.root / "run/candidates-top200.csv").read_text().splitlines()), 7)
        manifest = tf.read_json(self.root / "run/manifest.json")
        self.assertEqual(manifest["parameters"], tf.PARAMETERS)
        self.assertNotIn("k1", manifest["parameters"])

    def test_gold_changes_leave_prediction_bytes_unchanged(self):
        self.run_experiment("before")
        self.records[0]["test_changes"][0]["gold_test"] = "def test_alpha():\n    assert 'unrelated'\n"
        self.save_inputs()
        self.run_experiment("after")
        for pr in (1, 2, 3):
            self.assertEqual((self.root / f"before/predictions/pr-{pr}.json.gz").read_bytes(),
                             (self.root / f"after/predictions/pr-{pr}.json.gz").read_bytes())

    def test_retrieval_failures_stay_in_denominator(self):
        with patch.object(tf.TFIDFCosine, "rank", side_effect=ValueError("injected")):
            result = self.run_experiment()
        self.assertEqual(result["scored_pr_count"], 1)
        self.assertEqual(result["status_counts"]["RETRIEVAL_FAILED"], 1)
        self.assertEqual(result["metrics"]["200"]["macro_recall_at_k"], 0)
        self.assertEqual(tf.verify_run(self.root / "run")["status"], "PASS")

    def test_pairing_checks_input_documents_labels_and_rejects_mismatch(self):
        bm.run_experiment(inventory_path=self.inventory, raw_path=self.raw, bench=self.bench, output=self.root / "bm25")
        self.run_experiment()
        comparison = tf.compare_runs(self.root / "run", self.root / "bm25")
        self.assertEqual(comparison["paired_input_check"], "PASS")
        self.assertEqual(comparison["scored_pr_count"], 1)
        row_path = self.root / "run/per-pr.json"
        rows = json.loads(row_path.read_text())
        rows[0]["query_sha256"] = "mutated"
        row_path.write_text(json.dumps(rows))
        with self.assertRaises(bm.BatchError) as caught:
            tf.compare_runs(self.root / "run", self.root / "bm25")
        self.assertEqual(caught.exception.code, "COMPARISON_INPUT_MISMATCH")

    def test_seal_mutation_prevents_label_access(self):
        original = tf.write_json

        def tamper(path, value):
            original(path, value)
            if path.name == "predictions-manifest.json":
                prediction = self.root / "run" / value["predictions"][0]["path"]
                prediction.write_bytes(prediction.read_bytes() + b"changed")

        with patch.object(tf, "write_json", side_effect=tamper), patch.object(tf, "build_labels") as labels:
            with self.assertRaises(bm.BatchError) as caught:
                self.run_experiment()
            self.assertEqual(caught.exception.code, "PREDICTION_SEAL_CHANGED")
            labels.assert_not_called()


if __name__ == "__main__":
    unittest.main()
