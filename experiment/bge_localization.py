"""BAAI/bge-base-en-v1.5 retrieval on the fixed Scrapy localization protocol.

Uses the official full-precision ONNX model, native WordPiece tokenizer,
CLS pooling, L2 normalization and cosine scores. Query instruction and
512-token right truncation are explicit parts of this retriever.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import csv
import gzip
import io
import json
import math
from pathlib import Path
import re
import sys
import time
import tokenize as python_tokenize
from typing import Any
from zoneinfo import ZoneInfo

from . import bm25_localization as shared
from . import tfidf_localization as lexical
from . import bge_encoder as backend
from .bge_encoder import BGEEncoder, BGERanker, MODEL_DIRECTORY, RUNTIME_ROOT, MODEL_REFERENCE
from .bm25_localization import (
    ROOT, BENCH, CUTOFFS, BatchError, canonical_sha256, sha256_file,
    query_from_raw, score_at_k, summarize, write_json, write_ranking,
    error_info, testcase_inventory, build_labels,
)

VERSION = "bge-base-en-v1.5-testcase-v1"
DEFAULT_BASELINE = lexical.DEFAULT_BASELINE
TOKENIZER_VERSION = "bge-native-uncased-wordpiece-v1"


def load_base_documents(bench: Path, base: str):
    index, metadata, counts = shared.load_corpus(bench, base)
    del counts
    repository = bench / "batch/baselines" / base / "repository"
    files, documents = {}, []
    for entry in metadata["entries"]:
        if entry["path"] not in files:
            data = (repository / entry["path"]).read_bytes()
            if sha256_file(repository / entry["path"]) != entry["file_sha256"]:
                raise BatchError("CORPUS_SOURCE_CHANGED", "Base test changed during document extraction")
            encoding, _ = python_tokenize.detect_encoding(io.BytesIO(data).readline)
            files[entry["path"]] = data.decode(encoding).splitlines(keepends=True)
        source = "".join(files[entry["path"]][entry["start_line"] - 1:entry["end_line"]])
        document = entry["path"] + "\n" + entry["qualified_name"] + "\n" + source
        import hashlib
        if hashlib.sha256(document.encode()).hexdigest() != entry["document_sha256"]:
            raise BatchError("DOCUMENT_CHANGED", "BGE and lexical document bytes differ")
        documents.append(document)
    return index, metadata, documents


def load_corpus(bench: Path, base: str, encoder: BGEEncoder, output: Path):
    started = time.perf_counter()
    index, metadata, documents = load_base_documents(bench, base)
    embeddings, stats = encoder.encode(documents)
    path = output / "vectors" / f"{base}.npy"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoder.np.save(path, embeddings, allow_pickle=False)
    metadata.update(retrieval_method=backend.MODEL_ID,
                    embedding_artifact={"path": str(path.relative_to(output)), "sha256": sha256_file(path)},
                    encoder_signature=encoder.signature, encoding_stats=stats,
                    truncated_document_count=sum(item["truncated"] for item in stats),
                    build_seconds=time.perf_counter() - started)
    return index, metadata, BGERanker([entry["id"] for entry in index["entries"]], embeddings, encoder)


def write_report(output: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    pct = lambda value: f"{value:.2%}" if value is not None else "N/A"
    manifest = read_json(output / "manifest.json")
    model = manifest["parameters"]
    corpora = [read_json(path) for path in (output / "corpora").glob("*.json")]
    documents = sum(corpus["document_count"] for corpus in corpora)
    truncated = sum(corpus["truncated_document_count"] for corpus in corpora)
    lines = ["# Scrapy BAAI/bge-base-en-v1.5 方法级候选召回", "",
             f"固定 {len(rows)} 个 PR；可评分 {summary['scored_pr_count']} 个。", "",
             "## 固定输入与模型配置", "",
             "沿用相同 PR 清单、base 快照、原始 title/body、测试身份与宿主机标签。",
             "文档仍为路径、完整限定名与完整方法源码，字节哈希与 BM25/TF-IDF 文档一致。",
             "BGE 使用模型自带 WordPiece 分词，取 CLS 向量，L2 归一化，再以余弦相似度排序。",
             "未对源码应用 BM25 的拆词/小写预处理；模型分词器自行处理文本。",
             f"固定模型版本：`{model['revision']}`；768 维，官方 ONNX FP32 权重，CPU 推理。",
             f"查询添加官方指令：`{model['query_instruction']}`；测试文档不加指令。",
             "输入超过 512 tokens 时保留开头并右截断，保留 CLS/SEP；不分块、不生成摘要。",
             f"模型与使用依据：[官方模型卡]({MODEL_REFERENCE})。", "",
             f"{len(corpora)} 个不同 base 共 {documents} 篇定义文档，其中 {truncated} 篇被截断。",
             "这里按 base 定义计数，同一测试跨 base 可能重复。",
             f"{len(rows)} 个查询中实际截断 {summary['encoding']['truncated_queries']} 个。", "",
             "严格 Top-50/100/200，无分数阈值；同分按测试身份排序，不足 k 则全取。",
             "排名和文档/查询向量全部封存校验后再构造标签。主标签为已有测试的可对齐内容修改；",
             "新增、删除、重命名、helper/fixture、AST 相同变化按原协议单列。", "",
             "## 汇总", "",
             "| k | Macro Recall@k | Hit@k 任务命中率 | Macro Precision@k | Micro Recall@k | 找全 PR |",
             "|---:|---:|---:|---:|---:|---:|"]
    for k in CUTOFFS:
        m = summary["metrics"][str(k)]
        lines.append(f"| {k} | {pct(m['macro_recall_at_k'])} | {pct(m['task_hit_rate_at_k'])} | "
                     f"{pct(m['macro_precision_at_k'])} | {pct(m['micro_recall'])} | {m['all_hit_pr_count']}/{m['scored_pr_count']} |")
    lines += ["", "Macro Recall@k：逐 PR 的召回率平均；Hit@k：至少命中一个目标的 PR 比例；",
              "Macro Precision@k：逐 PR 的候选命中比例平均；Micro Recall@k：总命中数/总参考目标数。", "",
              "## 任务状态", "", "| 状态 | 数量 |", "|---|---:|"]
    lines += [f"| {state} | {count} |" for state, count in summary["status_counts"].items()]
    lines += ["", "## 逐 PR 结果", "",
              "| PR | 状态 | 目标数 | Recall@50 | Recall@100 | Recall@200 | 查询截断 |",
              "|---:|---|---:|---:|---:|---:|---|"]
    for row in rows:
        values = [pct(row.get("metrics", {}).get(str(k), {}).get("recall")) for k in CUTOFFS]
        lines.append(f"| {row['pr_id']} | {row['status']} | {row.get('gold_count', '—')} | "
                     f"{' | '.join(values)} | {row.get('query_encoding', {}).get('truncated', '—')} |")
    problems = [row for row in rows if row["status"] != "SCORED"]
    if problems:
        lines += ["", "## 单列任务", ""]
        for row in problems:
            reason = {key: row[key] for key in ("error", "label_issues", "excluded_counts") if key in row}
            lines.append(f"- PR {row['pr_id']}：`{json.dumps(reason, ensure_ascii=False, sort_keys=True)}`")
    lines += ["", "## 成本与复现", "",
              f"本轮请求向量 {summary['encoding']['requests']} 次，新计算 {summary['encoding']['newly_computed']} 个，",
              f"缓存复用计数 {summary['encoding']['cache_hits']}。缓存按模型、编码配置及有效 token ID 哈希绑定。",
              "文档缓存预计算成本另见 cache-precompute.json（存在时），不与本轮暖缓存运行时长混淆。",
              "模型、依赖与实现哈希见 manifest.json；实际向量见 vectors/ 和 queries/*.npy；",
              "候选清单见 candidates-top200.csv；独立余弦/指标重算见 verification.json。",
              "主结果使用完整且有正目标的标签；检索失败以空预测计零，标签不完整与无正目标单列。",
              "不调参、不预设合格线；真实修改为代理标签，源码清单并非完整 pytest 动态收集。", "",
              "```bash",
              "/data2/wangzuohit/nlpu-bge/venv/bin/python -m experiment.bge_localization --output-dir /data2/wangzuohit/nlpu-bge/results/<new-run-id>",
              "```", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    with (output / "candidates-top200.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["pr_id", "base_sha", "rank", "score", "testcase_id", "in_top50", "in_top100", "in_top200"])
        writer.writeheader()
        for row in rows:
            if "prediction" not in row:
                continue
            for entry in read_ranking(output / row["prediction"]["path"])["ranking"][:200]:
                writer.writerow({"pr_id": row["pr_id"], "base_sha": row["base_sha"], "rank": entry["rank"],
                                 "score": entry["score"], "testcase_id": entry["id"],
                                 **{f"in_top{k}": int(entry["rank"] <= k) for k in CUTOFFS}})


read_json = lexical.read_json
read_ranking = lexical.read_ranking


def run_experiment(*, inventory_path: Path, raw_path: Path, bench: Path,
                   output: Path, encoder: BGEEncoder) -> dict[str, Any]:
    started = time.perf_counter()
    selection = json.loads(inventory_path.read_text(encoding="utf-8"))
    raw_sha = sha256_file(raw_path)
    if selection["inputs"]["raw"]["sha256"] != raw_sha:
        raise BatchError("RAW_SOURCE_CHANGED", "Raw input differs from the fixed inventory hash")
    prs = selection["pull_requests"]
    keys = [(item["repository"], item["pr_id"]) for item in prs]
    if len(set(keys)) != len(keys) or len(prs) != selection["summary"]["pr_count"]:
        raise BatchError("INVENTORY_INVALID", "PR identities/count are inconsistent")
    if any(repository != "scrapy/scrapy" or not isinstance(pr, int) or pr <= 0 for repository, pr in keys):
        raise BatchError("INVENTORY_SCOPE_INVALID", "Require positive Scrapy PR identities")
    raw_by_key: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for number, line in enumerate(raw_path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            record = json.loads(line)
            raw_by_key[(record.get("repo"), record.get("pr_id"))].append({"record": record, "line": number})
    output.mkdir(parents=True, exist_ok=False)
    # --bench selects data, while these are the modules actually executing.
    implementation_files = [Path(__file__), Path(shared.__file__), Path(lexical.__file__), Path(backend.__file__), *(Path(sys.modules[obj.__module__].__file__)
                            for obj in (BatchError, testcase_inventory, build_labels))]
    manifest = {
        "version": VERSION, "state": "RANKING", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bench": str(bench.resolve()),
        "inventory": {"path": str(inventory_path.resolve()), "sha256": sha256_file(inventory_path)},
        "raw": {"path": str(raw_path.resolve()), "sha256": raw_sha},
        "parameters": encoder.provenance, "cutoffs": list(CUTOFFS), "tokenizer": TOKENIZER_VERSION,
        "query": "raw title + two newlines + raw body; whitelist only",
        "document": "base path + qualified_name + full source including decorators",
        "similarity": "cosine of L2-normalized CLS embeddings", "encoder_signature": encoder.signature,
        "ties": "score descending, source identity ascending", "zero_scores": "included",
        "model_reference": MODEL_REFERENCE, "pr_count": len(prs), "python": sys.version,
        "user_confirmations": {"title_body_unedited": True, "selected_scope_is_intentional": True},
        "implementation_sha256": {str(path.resolve()): sha256_file(path) for path in implementation_files},
    }
    write_json(output / "manifest.json", manifest)
    corpus_cache, corpus_errors, rows, records = {}, {}, [], {}
    active_base, ranker = None, None
    seals = []
    # Phase 1: rank every query using base-only documents, never reference labels.
    # Group shared bases so only one postings index needs to stay in memory.
    for item in sorted(prs, key=lambda value: (str(value.get("recorded_base_sha")), value["pr_id"])):
        pr = item["pr_id"]
        row = {"repository": item["repository"], "pr_id": pr,
               "base_sha": item.get("recorded_base_sha"), "scorable": False}
        rows.append(row)
        candidates = raw_by_key.get((item["repository"], pr), [])
        try:
            if len(candidates) != 1:
                raise BatchError("RAW_IDENTITY_NOT_UNIQUE", "Require exactly one raw record", count=len(candidates))
            raw = candidates[0]["record"]
            base = row["base_sha"]
            if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base) or raw.get("base_sha") != base:
                raise BatchError("BASE_MISMATCH", "Inventory and raw base identity differ")
            row["raw_line"] = candidates[0]["line"]
            row["raw_record_sha256"] = canonical_sha256(raw)
            records[pr] = raw
            query = query_from_raw(raw)
            if base in corpus_errors:
                raise BatchError("BASE_CORPUS_UNAVAILABLE", "Earlier corpus validation failed", cause=corpus_errors[base])
            if base not in corpus_cache:
                try:
                    ranker = None
                    index, metadata, ranker = load_corpus(bench, base, encoder, output)
                except (BatchError, OSError, ValueError, KeyError) as error:
                    corpus_errors[base] = error_info(error)
                    raise
                write_json(output / "corpora" / f"{base}.json", metadata)
                corpus_cache[base] = index
                active_base = base
            index = corpus_cache[base]
            if active_base != base or ranker is None:
                raise BatchError("CORPUS_CACHE_INVALID", "Base grouping lost its active ranker")
            row["corpus_count"] = len(index["entries"])
            query_payload = {"title": raw["title"], "body": raw["body"]}
            write_json(output / "queries" / f"pr-{pr}.json", query_payload)
            row["query_sha256"] = canonical_sha256(query_payload)
            rank_started = time.perf_counter()
            ranking = ranker.rank(query)
            row["rank_seconds"] = time.perf_counter() - rank_started
            row["query_encoding"] = ranker.query_stats
            query_vector_path = output / "queries" / f"pr-{pr}.npy"
            encoder.np.save(query_vector_path, ranker.query_vector, allow_pickle=False)
            row["query_embedding"] = {"path": str(query_vector_path.relative_to(output)),
                                      "sha256": sha256_file(query_vector_path)}
            prediction = {"version": VERSION, "pr_id": pr, "base_sha": base,
                          "index_sha256": index["index_sha256"], "query_sha256": row["query_sha256"],
                          "corpus_count": len(ranking), "ranking": ranking,
                          "document_embedding": metadata["embedding_artifact"], "query_embedding": row["query_embedding"]}
            path = output / "predictions" / f"pr-{pr}.json.gz"
            write_ranking(path, prediction)
            seal = {"pr_id": pr, "path": str(path.relative_to(output)), "sha256": sha256_file(path)}
            seals.append(seal)
            row["prediction"] = seal
            row["status"] = "RANKED"
        except (BatchError, OSError, ValueError, KeyError, TypeError) as error:
            row["status"] = "RETRIEVAL_FAILED" if "corpus_count" in row else "INPUT_OR_BASE_INVALID"
            row["error"] = error_info(error)
        print(f"rank PR {pr}: {row['status']}", flush=True)
    rows.sort(key=lambda row: row["pr_id"])
    sealed = {"version": VERSION, "document_type": "BGE_PREDICTIONS_SEAL", "predictions": seals,
              "task_states": [{key: row[key] for key in ("pr_id", "status", "error") if key in row} for row in rows]}
    write_json(output / "predictions-manifest.json", sealed)
    manifest.update(state="EVALUATING", predictions_manifest_sha256=sha256_file(output / "predictions-manifest.json"))
    write_json(output / "manifest.json", manifest)
    # Verify ALL artifacts before any build_labels call. Fail closed on mutation.
    for seal in seals:
        if sha256_file(output / seal["path"]) != seal["sha256"]:
            raise BatchError("PREDICTION_SEAL_CHANGED", "Saved rankings differ from their seal")
    for seal in seals:
        prediction = read_ranking(output / seal["path"])
        for key in ("document_embedding", "query_embedding"):
            artifact = prediction[key]
            if sha256_file(output / artifact["path"]) != artifact["sha256"]:
                raise BatchError("EMBEDDING_SEAL_CHANGED", "Embedding differs before label access")
    # Phase 2: only the host evaluator receives raw test changes / gold.
    for row in rows:
        base, pr = row["base_sha"], row["pr_id"]
        if base not in corpus_cache or pr not in records:
            write_json(output / "evaluation" / f"pr-{pr}.json", row)
            continue
        try:
            labels = build_labels(records[pr], corpus_cache[base])
            row.update(gold_count=len(labels["testcases"]), labels_sha256=labels["labels_sha256"],
                       label_issues=labels["issues"], excluded_counts=labels["excluded_counts"])
            write_json(output / "evaluation" / f"pr-{pr}-labels.json", labels)
            if not labels["complete"]:
                row["status"] = "LABELS_INCOMPLETE"
            elif not labels["testcases"]:
                row["status"] = "NO_POSITIVE_GOLD"
            elif row["status"] in {"RANKED", "RETRIEVAL_FAILED"}:
                row["scorable"] = True
                ranking = []
                if row["status"] == "RANKED":
                    with gzip.open(output / row["prediction"]["path"], "rt", encoding="utf-8") as stream:
                        ranking = json.load(stream)["ranking"]
                    row["status"] = "SCORED"
                row["metrics"] = {str(k): score_at_k(ranking, labels["testcases"], k, row["corpus_count"])
                                  for k in CUTOFFS}
                positions = {entry["id"]: entry["rank"] for entry in ranking}
                row["gold_ranks"] = {identity: positions.get(identity) for identity in labels["testcases"]}
        except (BatchError, OSError, ValueError, KeyError, TypeError, SyntaxError) as error:
            row["status"] = "EVALUATION_FAILED"
            row["error"] = error_info(error)
            # Once positive labels are validated, evaluation/read failures score zero.
            if row.get("gold_count", 0) and not row.get("label_issues"):
                row["scorable"] = True
                row["metrics"] = {str(k): score_at_k([], labels["testcases"], k, row.get("corpus_count", 0))
                                  for k in CUTOFFS}
        write_json(output / "evaluation" / f"pr-{pr}.json", row)
    summary = summarize(rows)
    summary["total_seconds"] = time.perf_counter() - started
    summary["unique_base_count"] = len(corpus_cache)
    summary["invalid_bases"] = corpus_errors
    summary["encoding"] = {"requests": encoder.requests, "newly_computed": encoder.computed,
                           "cache_hits": encoder.cache_hits,
                           "truncated_queries": sum(row.get("query_encoding", {}).get("truncated", False) for row in rows)}
    write_json(output / "summary.json", summary)
    write_json(output / "per-pr.json", rows)
    with (output / "per-pr.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = ["pr_id", "base_sha", "status", "scorable", "corpus_count", "gold_count", "k",
                  "candidate_count", "matched_count", "precision", "recall", "hit_at_k", "all_hit", "zero_score_count"]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            for k in CUTOFFS:
                writer.writerow({**row, "k": k, **row.get("metrics", {}).get(str(k), {})})
    write_report(output, summary, rows)
    manifest.update(state="COMPLETE", completed_at_utc=datetime.now(timezone.utc).isoformat(),
                    total_seconds=summary["total_seconds"], status_counts=summary["status_counts"],
                    summary_sha256=sha256_file(output / "summary.json"),
                    report_sha256=sha256_file(output / "report.md"))
    write_json(output / "manifest.json", manifest)
    return summary


def verify_run(output: Path) -> dict[str, Any]:
    """Independently recompute counts/metrics from sealed predictions and labels."""
    manifest = read_json(output / "manifest.json")
    summary = read_json(output / "summary.json")
    rows = read_json(output / "per-pr.json")
    seal = read_json(output / "predictions-manifest.json")

    def require(condition, message):
        if not condition:
            raise BatchError("RUN_VERIFICATION_FAILED", message)

    require(manifest["state"] == "COMPLETE", "Run is incomplete")
    for name in ("summary", "report", "predictions-manifest"):
        key = "predictions_manifest_sha256" if name == "predictions-manifest" else name + "_sha256"
        suffix = ".md" if name == "report" else ".json"
        require(sha256_file(output / (name + suffix)) == manifest[key], f"Changed {name}")
    for source in ("inventory", "raw"):
        require(sha256_file(Path(manifest[source]["path"])) == manifest[source]["sha256"], f"Changed {source}")
    for name, digest in manifest["implementation_sha256"].items():
        require(sha256_file(Path(name)) == digest, "Implementation changed: " + name)
    import numpy as np
    predictions, matrices = {}, {}
    for item in seal["predictions"]:
        require(sha256_file(output / item["path"]) == item["sha256"], "Changed prediction")
        prediction = read_ranking(output / item["path"])
        ranking = prediction["ranking"]
        corpus = read_json(output / "corpora" / f"{prediction['base_sha']}.json")
        data_root = Path(manifest["bench"]).parents[1]
        require(sha256_file(data_root / corpus["baseline_lock"]["path"]) == corpus["baseline_lock"]["sha256"], "Changed baseline lock")
        require({entry["id"] for entry in ranking} == {entry["id"] for entry in corpus["entries"]}, "Incomplete candidate universe")
        require(len(ranking) == len(corpus["entries"]), "Duplicate ranking entries")
        require([entry["rank"] for entry in ranking] == list(range(1, len(ranking) + 1)), "Invalid rank sequence")
        require(ranking == sorted(ranking, key=lambda entry: (-entry["score"], entry["id"])), "Invalid sorting")
        require(all(math.isfinite(entry["score"]) and -1 - 1e-6 <= entry["score"] <= 1 + 1e-6 for entry in ranking), "Invalid cosine value")
        query = read_json(output / "queries" / f"pr-{item['pr_id']}.json")
        require(set(query) == {"title", "body"} and canonical_sha256(query) == prediction["query_sha256"], "Invalid query whitelist/hash")
        require(prediction["index_sha256"] == corpus["index_sha256"], "Invalid corpus identity")
        for key in ("document_embedding", "query_embedding"):
            artifact = prediction[key]
            require(sha256_file(output / artifact["path"]) == artifact["sha256"], "Changed embedding")
        matrix_path = prediction["document_embedding"]["path"]
        if matrix_path not in matrices:
            matrix = np.load(output / matrix_path, allow_pickle=False)
            require(matrix.shape == (len(corpus["entries"]), 768), "Invalid matrix shape")
            require(np.isfinite(matrix).all() and np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-4), "Invalid document norms")
            matrices[matrix_path] = matrix
        vector = np.load(output / prediction["query_embedding"]["path"], allow_pickle=False)
        require(vector.shape == (768,) and abs(float(np.linalg.norm(vector)) - 1) < 1e-4, "Invalid query norm")
        scores = matrices[matrix_path] @ vector
        positions = {entry["id"]: i for i, entry in enumerate(corpus["entries"])}
        require(all(math.isclose(entry["score"], float(scores[positions[entry["id"]]]), rel_tol=1e-5, abs_tol=1e-6)
                    for entry in ranking), "Cosine recomputation mismatch")
        predictions[item["pr_id"]] = ranking
    recomputed = {str(k): [] for k in CUTOFFS}
    for row in rows:
        if not row["scorable"]:
            continue
        labels = read_json(output / "evaluation" / f"pr-{row['pr_id']}-labels.json")
        digest = labels.pop("labels_sha256")
        require(canonical_sha256(labels) == digest == row["labels_sha256"], "Changed labels")
        require(labels["complete"] and bool(labels["testcases"]), "Invalid scorable task")
        gold = set(labels["testcases"])
        ranking = predictions.get(row["pr_id"], [])
        for k in CUTOFFS:
            prefix = ranking[:k]
            hits = len(gold & {entry["id"] for entry in prefix})
            count = len(prefix)
            value = {"tp": hits, "gold_count": len(gold), "candidate_count": count,
                     "recall": hits / len(gold), "precision": hits / count if count else 0.0,
                     "hit_at_k": int(hits > 0), "all_hit": int(hits == len(gold)),
                     "zero_score_count": sum(entry["score"] == 0 for entry in prefix)}
            actual = row["metrics"][str(k)]
            require(all(math.isclose(actual[key], number) for key, number in value.items()), "Per-PR metric mismatch")
            recomputed[str(k)].append(value)
    for k, values in recomputed.items():
        n = len(values)
        require(n == summary["scored_pr_count"], "Invalid score denominator")
        if not n:
            continue
        hits = sum(value["tp"] for value in values)
        targets = sum(value["gold_count"] for value in values)
        metrics = summary["metrics"][k]
        for name, expected in {
            "macro_recall_at_k": sum(value["recall"] for value in values) / n,
            "macro_precision_at_k": sum(value["precision"] for value in values) / n,
            "task_hit_rate_at_k": sum(value["hit_at_k"] for value in values) / n,
            "micro_recall": hits / targets,
            "all_hit_pr_count": sum(value["all_hit"] for value in values),
            "matched_count": hits, "gold_count": targets,
            "zero_score_candidate_count": sum(value["zero_score_count"] for value in values),
        }.items():
            require(math.isclose(metrics[name], expected), "Aggregate mismatch: " + name)
    require(len(rows) == summary["pr_count"], "Missing task accounting")
    result = {"status": "PASS", "pr_count": len(rows), "ranked_pr_count": len(predictions),
              "scored_pr_count": summary["scored_pr_count"],
              "source_manifest_sha256": sha256_file(output / "manifest.json"),
              "checks": ["input/code/report hashes", "prediction seals", "corpus and query identities",
                         "complete deterministic rankings", "cosine scores recomputed from saved normalized vectors", "per-PR and aggregate metrics independently recomputed"]}
    for name, digest in manifest["parameters"]["files_sha256"].items():
        require(sha256_file(Path(manifest["parameters"]["model_directory"]) / name) == digest, "Changed model file")
    write_json(output / "verification.json", result)
    return result


def compare_runs(output: Path, baselines: dict[str, Path]):
    current_manifest = read_json(output / "manifest.json")
    current_rows = {row["pr_id"]: row for row in read_json(output / "per-pr.json")}
    summaries = {"BGE": read_json(output / "summary.json")}
    identities = {"BGE": {"path": str(output.resolve()), "manifest_sha256": sha256_file(output / "manifest.json")}}
    pairs = []
    for method, baseline in baselines.items():
        previous_manifest = read_json(baseline / "manifest.json")
        previous_rows = {row["pr_id"]: row for row in read_json(baseline / "per-pr.json")}

        def require(condition, message):
            if not condition:
                raise BatchError("COMPARISON_INPUT_MISMATCH", f"{method}: {message}")

        require(previous_manifest["state"] == current_manifest["state"] == "COMPLETE", "incomplete run")
        for field in ("inventory", "raw"):
            require(previous_manifest[field]["sha256"] == current_manifest[field]["sha256"], f"different {field}")
        # Model-specific tokenization/instruction/truncation are explicit parts
        # of BGE. Raw query/document bytes and candidate/label identities match.
        for field in ("cutoffs", "query", "document", "ties", "zero_scores"):
            require(previous_manifest[field] == current_manifest[field], f"different {field}")
        for name in ("summary", "report", "predictions-manifest"):
            key = "predictions_manifest_sha256" if name == "predictions-manifest" else name + "_sha256"
            extension = ".md" if name == "report" else ".json"
            require(sha256_file(baseline / (name + extension)) == previous_manifest[key], f"changed {name}")
        require(previous_rows.keys() == current_rows.keys(), "different PR scope")
        for pr, row in current_rows.items():
            for field in ("repository", "base_sha", "query_sha256", "corpus_count", "scorable", "gold_count", "labels_sha256"):
                require(row.get(field) == previous_rows[pr].get(field), f"PR {pr}: different {field}")
            if row["scorable"]:
                for k in CUTOFFS:
                    a, b = row["metrics"][str(k)], previous_rows[pr]["metrics"][str(k)]
                    pairs.append({"baseline": method, "pr_id": pr, "k": k, "gold_count": row["gold_count"],
                                  "baseline_hits": b["tp"], "bge_hits": a["tp"],
                                  "baseline_recall": b["recall"], "bge_recall": a["recall"],
                                  "recall_delta_pp": (a["recall"] - b["recall"]) * 100})
        for path in (output / "corpora").glob("*.json"):
            a, b = read_json(path), read_json(baseline / "corpora" / path.name)
            for field in ("base_sha", "baseline_lock", "index_sha256", "entries", "document_count"):
                require(a[field] == b[field], f"corpus {path.stem}: different {field}")
        summaries[method] = read_json(baseline / "summary.json")
        identities[method] = {"path": str(baseline.resolve()), "manifest_sha256": sha256_file(baseline / "manifest.json")}
    result = {"paired_input_check": "PASS", "runs": identities, "summaries": summaries,
              "model_specific_differences": ["native WordPiece", "official query instruction", "512-token right truncation"]}
    write_json(output / "comparison.json", result)
    with (output / "comparison-per-pr.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = list(pairs[0]) if pairs else ["baseline", "pr_id", "k"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(pairs)
    lines = ["# BGE、BM25 与 TF-IDF 的同范围对照", "",
             f"同一批 {len(current_rows)} 个 PR，可评分 {summaries['BGE']['scored_pr_count']} 个。",
             "已校验原始查询、base、完整候选文档字节、参考标签、PR 范围与指标分母一致。",
             "BGE 的模型分词、查询指令及 512-token 截断属于已记录的模型配置。", "",
             "| k | 方法 | Macro Recall@k | Hit@k | Macro Precision@k | Micro Recall@k | 命中目标 | 找全 PR |",
             "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for k in CUTOFFS:
        for method in (*baselines, "BGE"):
            m = summaries[method]["metrics"][str(k)]
            if m["macro_recall_at_k"] is None:
                continue
            lines.append(f"| {k} | {method} | {m['macro_recall_at_k']:.2%} | {m['task_hit_rate_at_k']:.2%} | "
                         f"{m['macro_precision_at_k']:.2%} | {m['micro_recall']:.2%} | {m['matched_count']} | {m['all_hit_pr_count']} |")
    lines += ["", "## 逐 PR 的召回变化", "",
              "| k | 对照 | BGE 较好 PR | BGE 较差 PR | 持平 PR |", "|---:|---|---:|---:|---:|"]
    for k in CUTOFFS:
        for method in baselines:
            selected = [row for row in pairs if row["k"] == k and row["baseline"] == method]
            wins = sum(row["recall_delta_pp"] > 0 for row in selected)
            losses = sum(row["recall_delta_pp"] < 0 for row in selected)
            lines.append(f"| {k} | {method} | {wins} | {losses} | {len(selected)-wins-losses} |")
    lines += ["", "本轮不调参，不预设有效阈值。结果限定于这批任务和当前配置，未做统计显著性检验。",
              "完整配置与截断统计见 [report.md](report.md)，逐 PR 差异见 [comparison-per-pr.csv](comparison-per-pr.csv)，",
              "候选清单见 [candidates-top200.csv](candidates-top200.csv)，独立向量/指标重算见 [verification.json](verification.json)。", ""]
    (output / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=BENCH / "batch/inventories/scrapy-pr-inventory.json")
    parser.add_argument("--raw-prs", type=Path, default=ROOT / "output/raw_prs/scrapy__scrapy.jsonl")
    parser.add_argument("--bench", type=Path, default=BENCH)
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIRECTORY)
    parser.add_argument("--embedding-cache", type=Path, default=RUNTIME_ROOT / "cache/embeddings.sqlite3")
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=16)
    run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S%z")
    parser.add_argument("--output-dir", type=Path, default=RUNTIME_ROOT / "results" / run_id)
    parser.add_argument("--bm25-run", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--tfidf-run", type=Path, default=ROOT / "output/tfidf-localization/scrapy-98pr-20261027-v2")
    args = parser.parse_args()
    encoder = None
    try:
        encoder = BGEEncoder(args.model_dir, args.embedding_cache, threads=args.threads, batch_size=args.batch_size)
        summary = run_experiment(inventory_path=args.inventory, raw_path=args.raw_prs, bench=args.bench,
                                 output=args.output_dir, encoder=encoder)
        verification = verify_run(args.output_dir)
        compare_runs(args.output_dir, {"BM25": args.bm25_run, "TF-IDF": args.tfidf_run})
        print(json.dumps({"output": str(args.output_dir.resolve()), "summary": summary, "verification": verification},
                         ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({"error": error_info(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if encoder is not None:
            encoder.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
