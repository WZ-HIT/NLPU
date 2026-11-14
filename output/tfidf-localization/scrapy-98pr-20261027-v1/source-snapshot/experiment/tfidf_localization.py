"""TF-IDF + cosine test retrieval with the same protocol as BM25.

python3 -m experiment.tfidf_localization --output-dir output/tfidf-localization/<run-id>

Raw TF, smoothed IDF log((N+1)/(df+1))+1, L2-normalized document/query
vectors, and cosine scores. Vocabulary and IDF are fitted on base tests only.
All rankings are sealed before host labels are constructed. Standard library
implementation; no model calls, network requests, or test execution.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import gzip
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any
from zoneinfo import ZoneInfo

from . import bm25_localization as shared
from .bm25_localization import (
    ROOT, BENCH, CUTOFFS, TOKENIZER_VERSION, BatchError, canonical_sha256,
    sha256_file, tokenize, query_from_raw, score_at_k, summarize, write_json,
    write_ranking, error_info, testcase_inventory, build_labels,
)

VERSION = "tfidf-cosine-testcase-v1"
PARAMETERS = {"tf": "raw_count", "norm": "l2", "use_idf": True,
              "smooth_idf": True, "sublinear_tf": False}
TFIDF_REFERENCE = "https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfTransformer.html"
COSINE_REFERENCE = "https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html"
DEFAULT_BASELINE = ROOT / "output/bm25-localization/scrapy-98pr-20261027-v1"


class TFIDFCosine:
    """Base-fitted TF-IDF vectors, cosine similarity and deterministic ties."""

    def __init__(self, documents: dict[str, list[str]]) -> None:
        postings = defaultdict(list)
        for identity in sorted(documents):
            for term, tf in Counter(documents[identity]).items():
                postings[term].append((identity, tf))
        self._fit(sorted(documents), postings)

    @classmethod
    def from_counts(cls, identities: list[str], postings: dict[str, list[tuple[str, int]]]):
        result = cls.__new__(cls)
        result._fit(identities, postings)
        return result

    def _fit(self, identities, postings) -> None:
        self.ids = sorted(identities)
        self.idf = {term: math.log((1 + len(self.ids)) / (1 + len(items))) + 1
                    for term, items in sorted(postings.items())}
        squared = dict.fromkeys(self.ids, 0.0)
        for term, items in sorted(postings.items()):
            for identity, tf in items:
                squared[identity] += (tf * self.idf[term]) ** 2
        norms = {identity: math.sqrt(value) for identity, value in squared.items()}
        self.postings = {term: [(identity, tf * self.idf[term] / norms[identity])
                                for identity, tf in items]
                         for term, items in sorted(postings.items())}

    def rank(self, query: str) -> list[dict[str, Any]]:
        weights = {term: tf * self.idf[term] for term, tf in sorted(Counter(tokenize(query)).items())
                   if term in self.idf}
        norm = math.sqrt(sum(weight ** 2 for weight in weights.values()))
        scores = dict.fromkeys(self.ids, 0.0)
        if norm:
            for term, weight in weights.items():
                for identity, doc_weight in self.postings[term]:
                    scores[identity] += (weight / norm) * doc_weight
        return [{"id": identity, "score": score, "rank": rank}
                for rank, (identity, score) in enumerate(
                    sorted(scores.items(), key=lambda item: (-item[1], item[0])), 1)]


def load_corpus(bench: Path, base: str):
    started = time.perf_counter()
    index, metadata, counts = shared.load_corpus(bench, base)
    # The shared corpus builder stores raw TF postings, independent of BM25
    # scoring. Reuse those exact counts; BM25.rank is never called.
    ranker = TFIDFCosine.from_counts(counts.ids, counts.postings)
    metadata.update(retrieval_method="tfidf-cosine", idf_sha256=canonical_sha256(ranker.idf),
                    vocabulary_size=len(ranker.idf), build_seconds=time.perf_counter() - started)
    return index, metadata, ranker


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_ranking(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def write_report(output: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    pct = lambda value: f"{value:.2%}" if value is not None else "N/A"
    lines = ["# Scrapy TF-IDF + 余弦相似度候选召回实验", "",
             f"固定 {len(rows)} 个 PR；可评分 {summary['scored_pr_count']} 个。", "",
             "## 固定协议", "",
             "沿用 BM25 的 PR 清单、base 快照、测试身份、完整方法源码、分词、参考标签及指标。",
             "查询为原始 title + body；文档为 base 测试路径、限定名和完整方法源码（含装饰器）。",
             "按下划线、驼峰、标点和数字边界拆分，统一小写；不做词干化或停用词过滤。",
             "TF 使用原始次数；IDF=log((N+1)/(df+1))+1；文档与查询均做 L2 归一化后取点积。",
             "词表与 IDF 仅拟合当前 base 测试集合；查询不参与拟合，未登录词忽略。",
             f"权重公式参考 [TfidfTransformer]({TFIDF_REFERENCE})，相似度参考 [cosine_similarity]({COSINE_REFERENCE})。",
             "独立标准库实现，不依赖 scikit-learn。空/OOV 查询全部得零分。",
             "严格取 Top-50/100/200，零分补足，同分按源码测试身份排序，不足 k 时全部返回。",
             "全部排名封存后再构造宿主机标签。主标签为可对齐到 base 的已有测试内容修改；",
             "新增、删除、重命名、helper/fixture、AST 相同变化分别排除。", "",
             "## 汇总", "",
             "| k | Macro Recall@k | Hit@k 任务命中率 | Macro Precision@k 候选命中率 | Micro Recall@k | 找全 PR |",
             "|---:|---:|---:|---:|---:|---:|"]
    for k in CUTOFFS:
        m = summary["metrics"][str(k)]
        lines.append(f"| {k} | {pct(m['macro_recall_at_k'])} | {pct(m['task_hit_rate_at_k'])} | "
                     f"{pct(m['macro_precision_at_k'])} | {pct(m['micro_recall'])} | {m['all_hit_pr_count']}/{m['scored_pr_count']} |")
    lines += ["", "Macro Recall@k：每 PR 召回率的平均。Hit@k：至少命中一个目标的 PR 比例。",
              "Macro Precision@k：每 PR 命中数/实际候选数的平均。Micro Recall@k：总命中数/总目标数。",
              "无正目标与标签不完整单列；有效正标签的检索失败按空预测计零并保留在分母。", "",
              "## 任务状态", "", "| 状态 | 数量 |", "|---|---:|"]
    lines += [f"| {state} | {count} |" for state, count in summary["status_counts"].items()]
    lines += ["", "## 逐 PR 结果", "",
              "| PR | 状态 | 目标数 | Recall@50 | Recall@100 | Recall@200 |",
              "|---:|---|---:|---:|---:|---:|"]
    for row in rows:
        recalls = [pct(row.get("metrics", {}).get(str(k), {}).get("recall")) for k in CUTOFFS]
        lines.append(f"| {row['pr_id']} | {row['status']} | {row.get('gold_count', '—')} | {' | '.join(recalls)} |")
        if row["status"] != "SCORED":
            reason = {key: row[key] for key in ("error", "label_issues", "excluded_counts") if key in row}
            lines += ["", f"PR {row['pr_id']} 单列原因：`{json.dumps(reason, ensure_ascii=False, sort_keys=True)}`", ""]
    lines += ["", "候选清单见 candidates-top200.csv；封存排名见 predictions/；",
              "标签与逐 PR 评价见 evaluation/；配置和来源哈希见 manifest.json。",
              "独立重算见 verification.json；同范围 BM25 对照见 comparison.md（完成对照时生成）。",
              "不预设合格线或最佳 k。开发者实际修改为代理标签，源码定义清单不等同于 pytest 动态收集。", "",
              "```bash", "python3 -m experiment.tfidf_localization --output-dir output/tfidf-localization/<new-run-id>", "```", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    with (output / "candidates-top200.csv").open("x", encoding="utf-8", newline="") as stream:
        fields = ["pr_id", "base_sha", "rank", "score", "testcase_id", "in_top50", "in_top100", "in_top200"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            if "prediction" not in row:
                continue
            ranking = read_ranking(output / row["prediction"]["path"])["ranking"]
            for entry in ranking[:max(CUTOFFS)]:
                writer.writerow({"pr_id": row["pr_id"], "base_sha": row["base_sha"], "rank": entry["rank"],
                                 "score": entry["score"], "testcase_id": entry["id"],
                                 **{f"in_top{k}": int(entry["rank"] <= k) for k in CUTOFFS}})


def run_experiment(*, inventory_path: Path, raw_path: Path, bench: Path,
                   output: Path) -> dict[str, Any]:
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
    implementation_files = [Path(__file__), Path(shared.__file__), *(Path(sys.modules[obj.__module__].__file__)
                            for obj in (BatchError, testcase_inventory, build_labels))]
    manifest = {
        "version": VERSION, "state": "RANKING", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bench": str(bench.resolve()),
        "inventory": {"path": str(inventory_path.resolve()), "sha256": sha256_file(inventory_path)},
        "raw": {"path": str(raw_path.resolve()), "sha256": raw_sha},
        "parameters": PARAMETERS, "cutoffs": list(CUTOFFS), "tokenizer": TOKENIZER_VERSION,
        "query": "raw title + two newlines + raw body; whitelist only",
        "document": "base path + qualified_name + full source including decorators",
        "idf": "log((1+N)/(1+df))+1", "query_term_frequency": "raw counts; ignore out-of-vocabulary terms",
        "ties": "score descending, source identity ascending", "zero_scores": "included",
        "tfidf_reference": TFIDF_REFERENCE, "pr_count": len(prs), "python": sys.version,
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
                    index, metadata, ranker = load_corpus(bench, base)
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
            prediction = {"version": VERSION, "pr_id": pr, "base_sha": base,
                          "index_sha256": index["index_sha256"], "query_sha256": row["query_sha256"],
                          "corpus_count": len(ranking), "ranking": ranking}
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
    sealed = {"version": VERSION, "document_type": "TFIDF_COSINE_PREDICTIONS_SEAL", "predictions": seals,
              "task_states": [{key: row[key] for key in ("pr_id", "status", "error") if key in row} for row in rows]}
    write_json(output / "predictions-manifest.json", sealed)
    manifest.update(state="EVALUATING", predictions_manifest_sha256=sha256_file(output / "predictions-manifest.json"))
    write_json(output / "manifest.json", manifest)
    # Verify ALL artifacts before any build_labels call. Fail closed on mutation.
    for seal in seals:
        if sha256_file(output / seal["path"]) != seal["sha256"]:
            raise BatchError("PREDICTION_SEAL_CHANGED", "Saved rankings differ from their seal")
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
    predictions = {}
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
        require(all(math.isfinite(entry["score"]) and 0 <= entry["score"] <= 1 + 1e-12 for entry in ranking), "Invalid cosine value")
        query = read_json(output / "queries" / f"pr-{item['pr_id']}.json")
        require(set(query) == {"title", "body"} and canonical_sha256(query) == prediction["query_sha256"], "Invalid query whitelist/hash")
        require(prediction["index_sha256"] == corpus["index_sha256"], "Invalid corpus identity")
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
                         "complete deterministic rankings", "per-PR and aggregate metrics independently recomputed"]}
    write_json(output / "verification.json", result)
    return result


def compare_runs(output: Path, baseline: Path) -> dict[str, Any]:
    """Require paired input/label equivalence before comparing either ranking."""
    current_manifest = read_json(output / "manifest.json")
    baseline_manifest = read_json(baseline / "manifest.json")

    def mismatch(message):
        raise BatchError("COMPARISON_INPUT_MISMATCH", message)

    for name in ("inventory", "raw"):
        if current_manifest[name]["sha256"] != baseline_manifest[name]["sha256"]:
            mismatch("Different " + name)
    for key in ("cutoffs", "tokenizer", "query", "document", "ties", "zero_scores"):
        if current_manifest[key] != baseline_manifest[key]:
            mismatch("Different " + key)
    if current_manifest["state"] != "COMPLETE" or baseline_manifest["state"] != "COMPLETE":
        mismatch("Both runs must be complete")
    # Protect the original comparator as well as the new run.
    for name in ("summary", "report", "predictions-manifest"):
        key = "predictions_manifest_sha256" if name == "predictions-manifest" else name + "_sha256"
        suffix = ".md" if name == "report" else ".json"
        if sha256_file(baseline / (name + suffix)) != baseline_manifest[key]:
            mismatch("Changed baseline " + name)
    previous = {row["pr_id"]: row for row in read_json(baseline / "per-pr.json")}
    current = {row["pr_id"]: row for row in read_json(output / "per-pr.json")}
    if previous.keys() != current.keys():
        mismatch("Different PR scope")
    for pr, row in current.items():
        for key in ("repository", "base_sha", "query_sha256", "corpus_count", "scorable", "gold_count", "labels_sha256"):
            if row.get(key) != previous[pr].get(key):
                mismatch(f"PR {pr}: different {key}")
    for path in (output / "corpora").glob("*.json"):
        a, b = read_json(path), read_json(baseline / "corpora" / path.name)
        for key in ("base_sha", "baseline_lock", "index_sha256", "entries", "document_count"):
            if a[key] != b[key]:
                mismatch(f"Corpus {path.stem}: different {key}")
    newer, older = read_json(output / "summary.json"), read_json(baseline / "summary.json")
    fields = ("macro_recall_at_k", "task_hit_rate_at_k", "macro_precision_at_k", "micro_recall")
    metrics, pairs = {}, []
    for k in CUTOFFS:
        a, b = newer["metrics"][str(k)], older["metrics"][str(k)]
        values = {key: {"bm25": b[key], "tfidf_cosine": a[key], "delta_pp": (a[key] - b[key]) * 100}
                  for key in fields if a[key] is not None and b[key] is not None}
        paired = []
        for pr, row in current.items():
            if row["scorable"]:
                x, y = row["metrics"][str(k)], previous[pr]["metrics"][str(k)]
                paired.append(x["recall"] - y["recall"])
                pairs.append({"pr_id": pr, "k": k, "gold_count": row["gold_count"],
                              "bm25_hits": y["tp"], "tfidf_hits": x["tp"],
                              "bm25_recall": y["recall"], "tfidf_recall": x["recall"],
                              "recall_delta_pp": (x["recall"] - y["recall"]) * 100})
        metrics[str(k)] = {"metrics": values, "bm25_matched_count": b["matched_count"],
                           "tfidf_matched_count": a["matched_count"],
                           "tfidf_better_pr_count": sum(delta > 0 for delta in paired),
                           "tfidf_worse_pr_count": sum(delta < 0 for delta in paired),
                           "tie_pr_count": sum(delta == 0 for delta in paired)}
    comparison = {"paired_input_check": "PASS", "baseline": str(baseline.resolve()),
                  "baseline_manifest_sha256": sha256_file(baseline / "manifest.json"),
                  "current_manifest_sha256": sha256_file(output / "manifest.json"),
                  "pr_count": len(current), "scored_pr_count": newer["scored_pr_count"], "metrics": metrics}
    write_json(output / "comparison.json", comparison)
    with (output / "comparison-per-pr.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs[0]) if pairs else ["pr_id", "k"])
        writer.writeheader()
        writer.writerows(pairs)
    names = {"macro_recall_at_k": "Macro Recall@k", "task_hit_rate_at_k": "Hit@k 任务命中率",
             "macro_precision_at_k": "Macro Precision@k 候选命中率", "micro_recall": "Micro Recall@k"}
    lines = ["# TF-IDF + 余弦相似度与 BM25 对比", "",
             f"同一批 {len(current)} 个 PR，其中 {newer['scored_pr_count']} 个可评分。",
             "已校验输入哈希、查询、base、候选源码文档、分词、评价标签及评分 PR 范围一致。", "",
             "TF-IDF 使用原始 TF、平滑 IDF 与 L2 归一化，仅在各 base 测试集合拟合。",
             f"公式依据：[TfidfTransformer]({TFIDF_REFERENCE})。", "",
             "| k | 指标 | BM25 | TF-IDF + 余弦 | 差值（百分点） |",
             "|---:|---|---:|---:|---:|"]
    for k, data in metrics.items():
        for field, value in data["metrics"].items():
            lines.append(f"| {k} | {names[field]} | {value['bm25']:.2%} | {value['tfidf_cosine']:.2%} | {value['delta_pp']:+.2f} |")
    lines += ["", "## 命中目标数量与逐 PR 差异", "",
              "| k | BM25 命中目标 | TF-IDF 命中目标 | TF-IDF 较好 PR | 较差 PR | 持平 PR |",
              "|---:|---:|---:|---:|---:|---:|"]
    for k, data in metrics.items():
        lines.append(f"| {k} | {data['bm25_matched_count']} | {data['tfidf_matched_count']} | "
                     f"{data['tfidf_better_pr_count']} | {data['tfidf_worse_pr_count']} | {data['tie_pr_count']} |")
    lines += ["", "较好/较差按同一 PR 的 Recall@k 比较。结果仅解释当前固定样本与配置，未进行统计显著性检验。",
              "完整结果见 [report.md](report.md)，逐 PR 对照见 [comparison-per-pr.csv](comparison-per-pr.csv)，",
              "候选清单见 [candidates-top200.csv](candidates-top200.csv)，独立重算见 [verification.json](verification.json)。", ""]
    (output / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=BENCH / "batch/inventories/scrapy-pr-inventory.json")
    parser.add_argument("--raw-prs", type=Path, default=ROOT / "output/raw_prs/scrapy__scrapy.jsonl")
    parser.add_argument("--bench", type=Path, default=BENCH)
    run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S%z")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/tfidf-localization" / run_id)
    parser.add_argument("--compare-with", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()
    try:
        summary = run_experiment(inventory_path=args.inventory, raw_path=args.raw_prs, bench=args.bench, output=args.output_dir)
        verification = verify_run(args.output_dir)
        comparison = compare_runs(args.output_dir, args.compare_with)
    except (BatchError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"error": error_info(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output_dir.resolve()), "summary": summary,
                      "verification": verification, "comparison": comparison}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
