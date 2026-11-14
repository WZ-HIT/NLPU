from __future__ import annotations

import copy
import json
import sqlite3
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from experiment import bge_encoder as be
from experiment import bge_localization as bg
from experiment import bm25_localization as bm
from tests import test_bm25_localization as fixtures


class TinyTokenizer:
    def __init__(self):
        self.seen = []

    def encode_batch(self, texts, add_special_tokens):
        self.seen.extend(texts)
        assert add_special_tokens is False
        return [SimpleNamespace(ids=[5] * len(text.split())) for text in texts]


class TinySession:
    def __init__(self):
        self.inputs = []

    def run(self, outputs, inputs):
        self.inputs.append(copy.deepcopy(inputs))
        n, length = inputs["input_ids"].shape
        values = np.zeros((n, length, 768), dtype=np.float32)
        values[:, 0, 0] = 2
        values[:, 0, 1] = inputs["attention_mask"].sum(axis=1)
        return [values]


class EncoderTests(unittest.TestCase):
    def make_encoder(self):
        encoder = be.BGEEncoder.__new__(be.BGEEncoder)
        encoder.np = np
        encoder.batch_size, encoder.max_length = 4, 512
        encoder.cls, encoder.sep, encoder.pad = 101, 102, 0
        encoder.tokenizer, encoder.session = TinyTokenizer(), TinySession()
        encoder.output_name, encoder.signature = "last_hidden_state", "test-signature"
        encoder.memory = {}
        encoder.cache = sqlite3.connect(":memory:")
        encoder.cache.execute("CREATE TABLE vectors(key TEXT PRIMARY KEY,value BLOB)")
        self.addCleanup(encoder.close)
        encoder.requests = encoder.computed = encoder.cache_hits = 0
        encoder.last_progress = time.monotonic()
        return encoder

    def test_instruction_only_for_query_and_native_512_truncation(self):
        encoder = self.make_encoder()
        documents, stats = encoder.encode(["word " * 600, "short doc"])
        self.assertEqual(stats[0]["token_count"], 602)
        self.assertEqual(stats[0]["used_token_count"], 512)
        self.assertTrue(stats[0]["truncated"])
        self.assertFalse(stats[1]["truncated"])
        inputs = encoder.session.inputs[0]
        for row, mask in zip(inputs["input_ids"], inputs["attention_mask"]):
            self.assertEqual(row[0], 101)
            self.assertEqual(row[int(mask.sum()) - 1], 102)
        encoder.encode(["search"], query=True)
        self.assertEqual(encoder.tokenizer.seen[-1], be.QUERY_INSTRUCTION + "search")
        self.assertEqual(encoder.tokenizer.seen[1], "short doc")
        self.assertTrue(np.allclose(np.linalg.norm(documents, axis=1), 1))

    def test_cache_is_bound_to_effective_tokens_and_encoder(self):
        encoder = self.make_encoder()
        first, _ = encoder.encode(["long " * 600])
        computed = encoder.computed
        second, _ = encoder.encode(["long " * 700])
        self.assertEqual(encoder.computed, computed)
        self.assertTrue(np.array_equal(first, second))
        encoder.memory.clear()
        encoder.encode(["long " * 700])
        self.assertEqual(encoder.computed, computed)  # SQLite reuse too.
        encoder.signature = "different-model-or-config"
        encoder.encode(["long " * 700])
        self.assertEqual(encoder.computed, computed + 1)

    def test_cosine_sorting_negative_values_and_stable_ties(self):
        encoder = SimpleNamespace(encode=lambda texts, query: (np.eye(1, 768, dtype=np.float32), [{}]))
        vectors = np.zeros((3, 768), dtype=np.float32)
        vectors[:, 0] = [1, 1, -1]
        ranker = be.BGERanker(["a", "b", "c"], vectors, encoder)
        ranked = ranker.rank("query")
        self.assertEqual([row["id"] for row in ranked], ["a", "b", "c"])
        self.assertEqual([row["score"] for row in ranked], [1, 1, -1])


class FakeEncoder:
    np = np
    signature = "fake-encoder-test-only"

    def __init__(self):
        self.requests = self.computed = self.cache_hits = 0
        self.provenance = {"revision": "TEST-ONLY-NOT-A-MODEL", "query_instruction": be.QUERY_INSTRUCTION,
                           "files_sha256": {}, "model_directory": "/unused"}

    def encode(self, texts, query=False):
        self.requests += len(texts)
        self.computed += len(texts)
        vectors = np.zeros((len(texts), 768), dtype=np.float32)
        for i, text in enumerate(texts):
            vectors[i, 0 if "alpha" in text else 1] = 1
        return vectors, [{"truncated": False} for _ in texts]


class PipelineTests(unittest.TestCase):
    setUp = fixtures.ExperimentTests.setUp
    save_inputs = fixtures.ExperimentTests.save_inputs

    def run_experiment(self, name="run"):
        return bg.run_experiment(inventory_path=self.inventory, raw_path=self.raw, bench=self.bench,
                                 output=self.root / name, encoder=FakeEncoder())

    def test_full_protocol_same_documents_seal_before_gold_and_verify_cosines(self):
        original = bg.build_labels

        def after_seal(raw, index):
            self.assertTrue((self.root / "run/predictions-manifest.json").exists())
            self.assertEqual(len(list((self.root / "run/queries").glob("*.npy"))), 3)
            return original(raw, index)

        with patch.object(bg, "build_labels", side_effect=after_seal):
            summary = self.run_experiment()
        self.assertEqual(summary["status_counts"], {"LABELS_INCOMPLETE": 1, "NO_POSITIVE_GOLD": 1, "SCORED": 1})
        self.assertEqual(bg.verify_run(self.root / "run")["status"], "PASS")
        bm.run_experiment(inventory_path=self.inventory, raw_path=self.raw, bench=self.bench, output=self.root / "bm25")
        self.assertEqual(bg.compare_runs(self.root / "run", {"BM25": self.root / "bm25"})["paired_input_check"], "PASS")

    def test_gold_does_not_influence_vectors_or_predictions(self):
        self.run_experiment("before")
        self.records[0]["test_changes"][0]["gold_test"] = "def test_alpha():\n    assert 'different label'\n"
        self.save_inputs()
        self.run_experiment("after")
        for pr in (1, 2, 3):
            for subpath in (f"predictions/pr-{pr}.json.gz", f"queries/pr-{pr}.npy"):
                self.assertEqual((self.root / "before" / subpath).read_bytes(), (self.root / "after" / subpath).read_bytes())

    def test_vector_mutation_blocks_gold_access(self):
        original = bg.write_json

        def tamper(path, value):
            original(path, value)
            if path.name == "predictions-manifest.json":
                vector = self.root / "run/queries/pr-1.npy"
                vector.write_bytes(vector.read_bytes() + b"changed")

        with patch.object(bg, "write_json", side_effect=tamper), patch.object(bg, "build_labels") as labels:
            with self.assertRaises(bm.BatchError) as caught:
                self.run_experiment()
            self.assertEqual(caught.exception.code, "EMBEDDING_SEAL_CHANGED")
            labels.assert_not_called()


if __name__ == "__main__":
    unittest.main()
