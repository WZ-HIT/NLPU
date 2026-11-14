"""Pinned jinaai/jina-embeddings-v2-base-code ONNX/CPU encoder and reusable local cache.

Optional dependencies are imported only when constructing an encoder, keeping
the existing lexical baselines usable without a model runtime.
"""
from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import sqlite3
import time

from .bm25_localization import canonical_sha256, sha256_file

MODEL_ID = "jinaai/jina-embeddings-v2-base-code"
REVISION = "516f4baf13dec4ddddda8631e019b5737c8bc250"
MODEL_SHA256 = "63363fc178428b74620c6f3780cbc7191883fa5c7f84c0945c45eb5c4256733b"
QUERY_INSTRUCTION = ""
MODEL_REFERENCE = "https://huggingface.co/jinaai/jina-embeddings-v2-base-code"
RUNTIME_ROOT = Path("/data2/wangzuohit/nlpu-jina-code")
MODEL_DIRECTORY = RUNTIME_ROOT / "models" / ("jina-embeddings-v2-base-code-" + REVISION)


class JinaEncoder:
    def __init__(self, model_directory: Path, cache: Path, *, threads: int = 16,
                 batch_size: int = 16, max_length: int = 8192):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if not 2 < max_length <= 8192 or threads <= 0 or batch_size <= 0:
            raise ValueError("Require 2 < max_length <= 8192 and positive threads/batch_size")
        self.np = np
        self.batch_size, self.max_length = batch_size, max_length
        files = {name: sha256_file(model_directory / name)
                 for name in ("model.onnx", "tokenizer.json", "config.json", "tokenizer_config.json")}
        if files["model.onnx"] != MODEL_SHA256:
            raise ValueError("Model does not match the pinned official ONNX LFS SHA-256")
        config = json.loads((model_directory / "config.json").read_text())
        if config["hidden_size"] != 768 or config["max_position_embeddings"] != 8192:
            raise ValueError("Unexpected Jina code architecture")
        self.tokenizer = Tokenizer.from_file(str(model_directory / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.cls = self.tokenizer.token_to_id("<s>")
        self.sep = self.tokenizer.token_to_id("</s>")
        self.pad = self.tokenizer.token_to_id("<pad>")
        if (self.cls, self.sep, self.pad) != (0, 2, 1):
            raise ValueError("Unexpected RoBERTa special tokens")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(model_directory / "model.onnx"),
                                           sess_options=options, providers=["CPUExecutionProvider"])
        self.input_names = {value.name for value in self.session.get_inputs()}
        if self.input_names != {"input_ids", "attention_mask"}:
            raise ValueError("Unexpected ONNX input contract: " + str(self.input_names))
        self.output_name = self.session.get_outputs()[0].name
        self.provenance = {
            "model_id": MODEL_ID, "revision": REVISION, "model_directory": str(model_directory.resolve()),
            "files_sha256": files, "backend": "onnxruntime-cpu-float32", "pooling": "attention-mask mean",
            "normalize": "L2", "dimension": 768, "max_length": max_length,
            "truncation": "right; retain BOS/EOS; no chunking", "query_instruction": QUERY_INSTRUCTION,
            "document_instruction": "", "threads": threads, "batch_size": batch_size,
            "runtime_versions": {name: importlib.metadata.version(name)
                                 for name in ("onnxruntime", "tokenizers", "numpy")},
            "reference": MODEL_REFERENCE,
            "encoder_implementation_sha256": sha256_file(Path(__file__)),
        }
        self.signature = canonical_sha256({key: value for key, value in self.provenance.items()
                                           if key != "model_directory"})
        cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache = sqlite3.connect(cache)
        self.cache.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        self.memory = {}
        self.requests = self.computed = self.cache_hits = 0
        self.last_progress = time.monotonic()

    def encode(self, texts: list[str], *, query: bool = False):
        np = self.np
        prepared = [QUERY_INSTRUCTION + text if query else text for text in texts]
        encoded = self.tokenizer.encode_batch(prepared, add_special_tokens=False)
        ids_by_key, keys, stats = {}, [], []
        for encoding in encoded:
            original_length = len(encoding.ids) + 2
            ids = [self.cls, *encoding.ids[:self.max_length - 2], self.sep]
            key = canonical_sha256({"encoder": self.signature, "input_ids": ids})
            keys.append(key)
            stats.append({"token_count": original_length, "used_token_count": len(ids),
                          "truncated": original_length > self.max_length, "effective_input_sha256": key})
            ids_by_key[key] = ids
        self.requests += len(keys)
        missing = []
        for key in dict.fromkeys(keys):
            if key in self.memory:
                continue
            cached = self.cache.execute("SELECT value FROM vectors WHERE key=?", (key,)).fetchone()
            if cached:
                value = np.frombuffer(cached[0], dtype=np.float32).copy()
                self._validate_vector(value)
                self.memory[key] = value
            else:
                missing.append(key)
        self.cache_hits += len(keys) - len(missing)
        missing.sort(key=lambda key: (len(ids_by_key[key]), key))
        offset = 0
        while offset < len(missing):
            batch = missing[offset:offset + self.batch_size]
            longest = max(len(ids_by_key[key]) for key in batch)
            capacity = max(1, min(self.batch_size, (16 * 512 * 512) // (longest * longest)))
            batch = batch[:capacity]
            offset += len(batch)
            length = max(len(ids_by_key[key]) for key in batch)
            input_ids = np.full((len(batch), length), self.pad, dtype=np.int64)
            mask = np.zeros_like(input_ids)
            for i, key in enumerate(batch):
                ids = ids_by_key[key]
                input_ids[i, :len(ids)] = ids
                mask[i, :len(ids)] = 1
            inputs = {"input_ids": input_ids, "attention_mask": mask}
            output = self.session.run([self.output_name], inputs)[0]
            if output.ndim != 3 or output.shape[-1] != 768:
                raise ValueError("Expected last_hidden_state with 768 dimensions")
            hidden = output.astype(np.float32)
            weighted = hidden * mask[:, :, None].astype(np.float32)
            vectors = weighted.sum(axis=1) / mask.sum(axis=1, keepdims=True).astype(np.float32)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if not np.isfinite(norms).all() or (norms <= 0).any():
                raise ValueError("Invalid model embedding norms")
            vectors = vectors / norms
            for key, vector in zip(batch, vectors):
                self._validate_vector(vector)
                self.memory[key] = vector.copy()
                self.cache.execute("INSERT OR REPLACE INTO vectors(key,value) VALUES (?,?)",
                                   (key, vector.tobytes()))
            self.cache.commit()
            self.computed += len(batch)
            if time.monotonic() - self.last_progress >= 25:
                print(f"Jina embeddings: {self.computed} newly computed; {self.requests} requested", flush=True)
                self.last_progress = time.monotonic()
        return np.stack([self.memory[key] for key in keys]), stats

    def _validate_vector(self, vector):
        np = self.np
        if vector.shape != (768,) or not np.isfinite(vector).all() or abs(float(np.linalg.norm(vector)) - 1) > 1e-4:
            raise ValueError("Invalid normalized cached/model embedding")

    def close(self):
        self.cache.close()


# Ranking is model-independent once normalized 768-dimensional vectors exist.
from .bge_encoder import BGERanker as JinaRanker
