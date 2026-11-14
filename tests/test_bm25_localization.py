from __future__ import annotations

import copy
import gzip
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiment import bm25_localization as bm


class RankingTests(unittest.TestCase):
    def test_code_tokenization_is_shared_and_explicit(self):
        self.assertEqual(bm.tokenize("HTTPResponse snake_case parseURL2 tests/a.py 中文"),
                         ["http", "response", "snake", "case", "parse", "url", "2", "tests", "a", "py", "中文"])

    def test_scores_follow_fixed_formula_and_repeated_query_terms(self):
        ranker = bm.BM25({"b": ["alpha"], "a": ["alpha", "alpha", "other"], "c": ["other"]})
        ranking = ranker.rank("alpha")
        scores = {row["id"]: row["score"] for row in ranking}
        idf = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))
        expected = idf * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 3 / (5 / 3)))
        self.assertAlmostEqual(scores["a"], expected)
        self.assertGreater(scores["b"], scores["a"])
        self.assertEqual(scores["c"], 0)
        doubled = {row["id"]: row["score"] for row in ranker.rank("alpha alpha")}
        for identity, score in scores.items():
            self.assertAlmostEqual(doubled[identity], 2 * score)

    def test_oov_zero_scores_keep_all_candidates_and_stable_ties(self):
        ranker = bm.BM25({"z": ["same"], "a": ["same"], "m": []})
        for query in ("", "outofvocabulary"):
            self.assertEqual(ranker.rank(query), [
                {"id": "a", "rank": 1, "score": 0.0},
                {"id": "m", "rank": 2, "score": 0.0},
                {"id": "z", "rank": 3, "score": 0.0}])
        self.assertEqual([row["id"] for row in ranker.rank("same")], ["a", "z", "m"])

    def test_query_whitelist_ignores_all_answer_fields(self):
        raw = {"title": "a", "body": "b", "old_test": "secret", "gold_test": "secret",
               "test_changes": [{"gold_test": "secret"}], "comments": ["secret"]}
        self.assertEqual(bm.query_from_raw(raw), "a\n\nb")
        self.assertEqual(bm.query_from_raw({"title": "a", "body": "b"}), bm.query_from_raw(raw))

    def test_cutoffs_match_existing_ranked_evaluator_and_actual_denominator(self):
        from batch.evaluator import score_ranked
        ranking = [{"id": f"test-{i}", "score": 1.0 if i < 60 else 0.0, "rank": i + 1}
                   for i in range(180)]
        gold = ["test-2", "test-75", "test-170"]
        reference = score_ranked([row["id"] for row in ranking], gold, cutoffs=bm.CUTOFFS)
        for k in bm.CUTOFFS:
            with self.subTest(k=k):
                actual = bm.score_at_k(ranking, gold, k, len(ranking))
                prefix = score_ranked([row["id"] for row in ranking[:k]], gold)
                self.assertEqual(actual["recall"], reference[f"recall_at_{k}"])
                self.assertEqual(actual["hit_at_k"], reference[f"hit_at_{k}"])
                for field in ("tp", "fp", "fn", "precision", "recall", "all_hit"):
                    self.assertEqual(actual[field], prefix[field])
        self.assertEqual(bm.score_at_k(ranking, gold, 200, 180)["precision"], 3 / 180)
        self.assertEqual(bm.score_at_k(ranking, gold, 100, 180)["zero_score_count"], 40)

    def test_macro_micro_and_failed_retrieval_denominators(self):
        rows = [
            {"scorable": True, "status": "SCORED", "metrics": {
                str(k): bm.score_at_k([{"id": "a", "score": 1}], ["a"], k, 10) for k in bm.CUTOFFS}},
            {"scorable": True, "status": "RETRIEVAL_FAILED", "metrics": {
                str(k): bm.score_at_k([], ["a", "b", "c"], k, 10) for k in bm.CUTOFFS}},
            {"scorable": False, "status": "NO_POSITIVE_GOLD"},
            {"scorable": False, "status": "LABELS_INCOMPLETE"},
        ]
        result = bm.summarize(rows)
        self.assertEqual(result["scored_pr_count"], 2)
        self.assertEqual(result["metrics"]["50"]["macro_recall_at_k"], 0.5)
        self.assertEqual(result["metrics"]["50"]["micro_recall"], 0.25)
        self.assertEqual(result["metrics"]["50"]["task_hit_rate_at_k"], 0.5)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = "a" * 40
        self.bench = self.root / "bench"
        repo = self.bench / "batch/baselines" / self.base / "repository"
        (repo / "tests").mkdir(parents=True)
        self.old = "def test_alpha():\n    assert 1 == 1\n"
        source = (self.old + "\n@mark.parametrize('x', [1, 2])\n"
                  "def test_beta(x):\n    '''beta docs'''\n    assert x\n"
                  "\n@fixture\ndef test_fixture():\n    return 1\n")
        path = repo / "tests/test_sample.py"
        path.write_text(source)
        files = [{"path": "tests/test_sample.py", "sha256": bm.sha256_file(path)}]
        bm.write_json(repo.parent / "baseline-lock.json", {
            "base_sha": self.base, "checkout_files": files,
            "checkout_manifest_sha256": bm.canonical_sha256(files)})
        self.raw = self.root / "raw.jsonl"
        self.inventory = self.root / "inventory.json"
        modified = {"file": "tests/test_sample.py", "qualified_name": "test_alpha",
                    "change_type": "modified", "old_test": self.old,
                    "gold_test": self.old.replace("1 == 1", "1 == 2")}
        self.records = [{"repo": "scrapy/scrapy", "pr_id": i, "base_sha": self.base,
                         "title": "alpha", "body": "body", "test_changes": [copy.deepcopy(modified)]}
                        for i in (1, 2, 3)]
        self.records[1]["test_changes"][0]["gold_test"] = self.old
        self.records[2]["test_changes"][0]["old_test"] = self.old.replace("1 == 1", "1 == 3")
        self.save_inputs()

    def save_inputs(self):
        self.raw.write_text("".join(json.dumps(row) + "\n" for row in self.records))
        bm.write_json(self.inventory, {"inputs": {"raw": {"sha256": bm.sha256_file(self.raw)}},
                                     "summary": {"pr_count": len(self.records)},
                                     "pull_requests": [{"repository": "scrapy/scrapy", "pr_id": row["pr_id"],
                                                        "recorded_base_sha": self.base} for row in self.records]})

    def run_experiment(self, name="run"):
        return bm.run_experiment(inventory_path=self.inventory, raw_path=self.raw,
                                 bench=self.bench, output=self.root / name)

    def test_complete_run_seals_all_rankings_before_labels_and_reuses_full_corpus(self):
        original = bm.build_labels

        def after_seal(raw, index):
            self.assertEqual(len(list((self.root / "run/predictions").glob("*.gz"))), 3)
            self.assertTrue((self.root / "run/predictions-manifest.json").exists())
            return original(raw, index)

        with patch.object(bm, "build_labels", side_effect=after_seal):
            summary = self.run_experiment()
        self.assertEqual(summary["status_counts"], {"LABELS_INCOMPLETE": 1, "NO_POSITIVE_GOLD": 1, "SCORED": 1})
        self.assertEqual(summary["metrics"]["50"]["macro_recall_at_k"], 1)
        with gzip.open(self.root / "run/predictions/pr-1.json.gz", "rt") as stream:
            ranking = json.load(stream)["ranking"]
        self.assertEqual(len(ranking), 2)  # Unchanged beta included, fixture excluded.
        self.assertTrue(any(row["id"].endswith("test_beta") for row in ranking))
        corpus = json.loads(next((self.root / "run/corpora").glob("*.json")).read_text())
        self.assertEqual(corpus["entries"][1]["start_line"], 4)  # Includes decorator.
        self.assertEqual(json.loads((self.root / "run/manifest.json").read_text())["state"], "COMPLETE")
        self.assertTrue((self.root / "run/report.md").exists())
        self.assertTrue((self.root / "run/per-pr.csv").exists())

    def test_gold_changes_cannot_change_predictions(self):
        self.run_experiment("before")
        self.records[0]["test_changes"][0]["gold_test"] = "def test_alpha():\n    assert 'totally unrelated'\n"
        self.save_inputs()
        self.run_experiment("after")
        for pr in (1, 2, 3):
            self.assertEqual((self.root / f"before/predictions/pr-{pr}.json.gz").read_bytes(),
                             (self.root / f"after/predictions/pr-{pr}.json.gz").read_bytes())

    def test_retrieval_failure_is_preserved_and_scored_zero(self):
        with patch.object(bm.BM25, "rank", side_effect=ValueError("injected retrieval failure")):
            summary = self.run_experiment()
        self.assertEqual(summary["scored_pr_count"], 1)
        self.assertEqual(summary["status_counts"]["RETRIEVAL_FAILED"], 1)
        self.assertEqual(summary["metrics"]["200"]["macro_recall_at_k"], 0)

    def test_seal_mutation_blocks_every_gold_access(self):
        original = bm.write_json

        def mutate_after_seal(path, value):
            original(path, value)
            if path.name == "predictions-manifest.json":
                target = self.root / "run" / value["predictions"][0]["path"]
                target.write_bytes(target.read_bytes() + b"tampered")

        with patch.object(bm, "write_json", side_effect=mutate_after_seal), patch.object(bm, "build_labels") as labels:
            with self.assertRaises(bm.BatchError) as caught:
                self.run_experiment()
            self.assertEqual(caught.exception.code, "PREDICTION_SEAL_CHANGED")
            labels.assert_not_called()

    def test_changed_source_and_changed_raw_fail_closed(self):
        source = self.bench / "batch/baselines" / self.base / "repository/tests/test_sample.py"
        source.write_text(source.read_text() + "\n# mutation\n")
        summary = self.run_experiment()
        self.assertEqual(summary["scored_pr_count"], 0)
        self.assertEqual(summary["status_counts"], {"INPUT_OR_BASE_INVALID": 3})
        self.raw.write_text(self.raw.read_text() + "\n")
        with self.assertRaises(bm.BatchError) as caught:
            self.run_experiment("changed-raw")
        self.assertEqual(caught.exception.code, "RAW_SOURCE_CHANGED")
        self.assertFalse((self.root / "changed-raw").exists())

    def test_existing_run_cannot_be_overwritten(self):
        self.run_experiment()
        before = (self.root / "run/manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_experiment()
        self.assertEqual(before, (self.root / "run/manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
