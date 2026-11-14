"""Offline, method-level PR-to-test BM25 retrieval and host-only evaluation.

Run from NLPU with ``python3 -m experiment.bm25_localization``. Existing
testcase-v1 source identities/labels are reused; no tests, agents or network
requests are executed. All rankings are sealed before evaluation starts.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import gzip
import hashlib
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

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

from batch.core import BatchError, canonical_sha256, sha256_file
from batch.testcase_identity import inventory as testcase_inventory, verified_baseline
from batch.testcase_labels import build_labels

CUTOFFS = (50, 100, 200)
VERSION = "bm25-testcase-v1"
PARAMETERS = {"k1": 1.2, "b": 0.75}
TOKENIZER_VERSION = "unicode-alnum-camel-snake-digits-lower-v1"
BM25_REFERENCE = "https://lucene.apache.org/core/9_12_1/core/org/apache/lucene/search/similarities/BM25Similarity.html"


def tokenize(text: str) -> list[str]:
    """Split HTTPResponse, snake_case, punctuation and digit boundaries alike."""
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return [part.lower() for word in re.findall(r"[^\W_]+", text, re.UNICODE)
            for part in re.findall(r"[^\W\d_]+|\d+", word, re.UNICODE)]


def query_from_raw(raw: dict[str, Any]) -> str:
    # Deliberate whitelist: no old_test, patch, comments, commits or gold.
    title, body = raw.get("title"), raw.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise BatchError("QUERY_FIELDS_INVALID", "title and body must be strings")
    return title + "\n\n" + body


class BM25:
    """Exact BM25 with positive Lucene IDF and explicit token/document lengths.

    score(d,q) = sum(qtf * idf * tf * (k1+1) /
                     (tf + k1 * (1-b+b*len(d)/avgdl)))
    idf = log(1 + (N-df+0.5)/(df+0.5)). The constant k1+1 does not
    affect rankings. No stopword filtering, stemming or query-term deduping.
    """

    def __init__(self, documents: dict[str, list[str]], *, k1: float = 1.2,
                 b: float = 0.75) -> None:
        if not math.isfinite(k1) or k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("Require finite k1 > 0 and 0 <= b <= 1")
        self.ids = sorted(documents)
        self.k1, self.b = k1, b
        self.lengths = {identity: len(documents[identity]) for identity in self.ids}
        self.avgdl = sum(self.lengths.values()) / len(self.ids) if self.ids else 0.0
        self.postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for identity in self.ids:
            for term, frequency in Counter(documents[identity]).items():
                self.postings[term].append((identity, frequency))

    def rank(self, query: str) -> list[dict[str, Any]]:
        scores = dict.fromkeys(self.ids, 0.0)
        for term, qtf in sorted(Counter(tokenize(query)).items()):
            posting = self.postings.get(term, ())
            if not posting:
                continue
            idf = math.log1p((len(self.ids) - len(posting) + 0.5) / (len(posting) + 0.5))
            for identity, tf in posting:
                norm = self.k1 * (1 - self.b + self.b * self.lengths[identity] / self.avgdl)
                scores[identity] += qtf * idf * tf * (self.k1 + 1) / (tf + norm)
        return [{"id": identity, "score": score, "rank": rank}
                for rank, (identity, score) in enumerate(
                    sorted(scores.items(), key=lambda item: (-item[1], item[0])), 1)]


def score_at_k(ranking: list[dict[str, Any]], gold: list[str], k: int,
               corpus_count: int) -> dict[str, Any]:
    prefix = ranking[:k]
    ids = [item["id"] for item in prefix]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate prediction identities")
    reference = set(gold)
    hits = len(set(ids) & reference)
    return {
        "gold_count": len(reference), "candidate_count": len(ids), "matched_count": hits,
        "tp": hits, "fp": len(ids) - hits, "fn": len(reference) - hits,
        "precision": hits / len(ids) if ids else 0.0,
        "recall": hits / len(reference) if reference else 0.0,
        "recall_at_k": hits / len(reference) if reference else 0.0,
        "hit_at_k": int(hits > 0), "all_hit": int(bool(reference) and hits == len(reference)),
        "zero_score_count": sum(item["score"] == 0 for item in prefix),
        "candidate_fraction": len(ids) / corpus_count if corpus_count else 0.0,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # Retrieval failures with valid positive labels remain in the denominator.
    scored = [row for row in rows if row.get("scorable")]
    metrics = {}
    for k in CUTOFFS:
        values = [row["metrics"][str(k)] for row in scored]
        n = len(values)
        total = lambda key: sum(value[key] for value in values)
        mean = lambda key: total(key) / n if n else None
        gold, candidates, hits = total("gold_count"), total("candidate_count"), total("tp")
        metrics[str(k)] = {
            "scored_pr_count": n, "macro_recall_at_k": mean("recall"),
            "task_hit_rate_at_k": mean("hit_at_k"), "macro_precision_at_k": mean("precision"),
            "micro_recall": hits / gold if gold else None,
            "micro_precision": hits / candidates if candidates else None,
            "all_hit_pr_rate": mean("all_hit"), "hit_pr_count": total("hit_at_k"),
            "all_hit_pr_count": total("all_hit"), "matched_count": hits,
            "gold_count": gold, "returned_count": candidates,
            "mean_candidate_count": mean("candidate_count"),
            "mean_candidate_fraction": mean("candidate_fraction"),
            "zero_score_candidate_count": total("zero_score_count"),
        }
    return {"pr_count": len(rows), "scored_pr_count": len(scored),
            "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
            "metrics": metrics}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def write_ranking(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    with path.open("xb") as handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as stream:
            stream.write(payload)


def load_corpus(bench: Path, base: str) -> tuple[dict[str, Any], dict[str, Any], BM25]:
    started = time.perf_counter()
    repository, lock_reference = verified_baseline(bench, base)
    index = testcase_inventory(repository, base)
    if index["errors"]:
        raise BatchError("BASE_INDEX_INCOMPLETE", "Cannot rank an incomplete base corpus",
                         errors=index["errors"])
    documents, entries, files = {}, [], {}
    for entry in index["entries"]:
        path = repository / entry["path"]
        if entry["path"] not in files:
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["file_sha256"]:
                raise BatchError("CORPUS_SOURCE_CHANGED", "Source changed during corpus build")
            encoding, _ = python_tokenize.detect_encoding(io.BytesIO(data).readline)
            files[entry["path"]] = data.decode(encoding).splitlines(keepends=True)
        source = "".join(files[entry["path"]][entry["start_line"] - 1:entry["end_line"]])
        document = entry["path"] + "\n" + entry["qualified_name"] + "\n" + source
        terms = tokenize(document)
        documents[entry["id"]] = terms
        entries.append({**entry, "document_sha256": hashlib.sha256(document.encode()).hexdigest(),
                        "token_count": len(terms)})
    if not documents:
        raise BatchError("EMPTY_BASE_CORPUS", "No base testcase definitions found")
    ranker = BM25(documents, **PARAMETERS)
    metadata = {"base_sha": base, "baseline_lock": lock_reference,
                "index_sha256": index["index_sha256"], "entries": entries,
                "document_count": len(documents), "mean_document_tokens": ranker.avgdl,
                "build_seconds": time.perf_counter() - started}
    return index, metadata, ranker


def error_info(error: Exception) -> dict[str, Any]:
    if isinstance(error, BatchError):
        return error.as_dict()
    return {"code": type(error).__name__, "message": str(error)}


def write_report(output: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    pct = lambda value: f"{value:.2%}" if value is not None else "N/A"
    lines = ["# Scrapy BM25 方法级候选召回实验", "",
             f"固定范围 {len(rows)} 个 PR；可评分 {summary['scored_pr_count']} 个。", "",
             "用户确认：本批 title/body 未被编辑，98 个 PR 已经合理筛选。", "",
             "## 固定协议", "",
             "查询为原始 title + body；每个 PR 只检索其 base 的全部源码测试定义。",
             "文档为路径、限定名及完整方法源码。参数化合并，继承别名不展开。",
             "统一拆分下划线、驼峰、标点和数字边界，转小写，不过滤停用词或做词干化。",
             "BM25 k1=1.2、b=0.75，IDF=log(1+(N-df+0.5)/(df+0.5))；重复查询词按词频累加。",
             f"参数与 IDF 参考 [Lucene 官方文档]({BM25_REFERENCE})；本脚本独立实现，不等同于 Lucene 完整分析器。",
             "严格 Top-k，零分补足，同分按测试身份；不足 k 时返回全部。",
             "所有排名先封存，再由宿主机读取参考标签评分。标签来自整个 PR 的已有测试内容修改，",
             "排除新增、删除、重命名、helper/fixture、AST 相同变化；开发者改动是代理标签。", "",
             "## 汇总", "",
             "| k | Recall@k 宏平均 | 任务命中率 Hit@k | 候选命中率 Precision@k 宏平均 | 总体召回率 | 全部找回 PR |",
             "|---:|---:|---:|---:|---:|---:|"]
    for k in CUTOFFS:
        m = summary["metrics"][str(k)]
        lines.append(f"| {k} | {pct(m['macro_recall_at_k'])} | {pct(m['task_hit_rate_at_k'])} | "
                     f"{pct(m['macro_precision_at_k'])} | {pct(m['micro_recall'])} | "
                     f"{m['all_hit_pr_count']}/{m['scored_pr_count']} |")
    lines += ["", "Recall@k = 每 PR 命中目标数/目标数，再对可评分 PR 宏平均；",
              "任务命中率 = 至少命中一个目标的 PR 数/可评分 PR 数；",
              "候选命中率 = 每 PR 命中数/实际候选数，再宏平均；",
              "总体召回率 = 所有命中数之和/所有参考目标数之和。",
              "截断后 recall 与 recall_at_k 数值相同，不解释成独立结果。", "",
              "## 扩大候选集合的收益", "",
              "| k 变化 | 宏平均召回增加（百分点） | 新增命中目标 | 新增候选 | 新增命中 PR |",
              "|---|---:|---:|---:|---:|"]
    for before, after in zip(CUTOFFS, CUTOFFS[1:]):
        a, b = (summary["metrics"][str(k)] for k in (before, after))
        gain = ((b["macro_recall_at_k"] - a["macro_recall_at_k"]) * 100
                if a["macro_recall_at_k"] is not None else None)
        gain_text = f"{gain:.2f}" if gain is not None else "N/A"
        lines.append(f"| {before} → {after} | {gain_text} | {b['matched_count']-a['matched_count']} | "
                     f"{b['returned_count']-a['returned_count']} | {b['hit_pr_count']-a['hit_pr_count']} |")
    lines += ["", "## 候选与零分统计", "",
              "| k | 平均候选数 | 平均占全量测试比例 | 返回零分候选总数 |",
              "|---:|---:|---:|---:|"]
    for k in CUTOFFS:
        m = summary["metrics"][str(k)]
        count = m['mean_candidate_count']
        count_text = f"{count:.2f}" if count is not None else "N/A"
        lines.append(f"| {k} | {count_text} | {pct(m['mean_candidate_fraction'])} | {m['zero_score_candidate_count']} |")
    lines += ["", "## 完整任务状态", "",
              "标签完整且有正目标的检索失败任务保留在主指标分母，以空候选计零。",
              "输入/版本不符、标签不完整和无正目标任务分别列出，不进入常规召回分母。", "",
              "| 状态 | PR 数 |", "|---|---:|"]
    lines += [f"| {status} | {count} |" for status, count in summary["status_counts"].items()]
    lines += ["", "## 逐 PR 结果", "",
              "| PR | 状态 | 目标数 | 全量测试数 | Recall@50 | Recall@100 | Recall@200 |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        values = [pct(row.get("metrics", {}).get(str(k), {}).get("recall")) for k in CUTOFFS]
        lines.append(f"| {row['pr_id']} | {row['status']} | {row.get('gold_count', '—')} | "
                     f"{row.get('corpus_count', '—')} | {' | '.join(values)} |")
    problems = [row for row in rows if row["status"] != "SCORED"]
    if problems:
        lines += ["", "## 排除与失败原因", ""]
        for row in problems:
            reason = json.dumps({key: row[key] for key in ("error", "label_issues", "excluded_counts")
                                 if key in row}, ensure_ascii=False, sort_keys=True)
            lines.append(f"- PR {row['pr_id']}：{row['status']}；{reason}")
    lines += ["", "## 结果解释与复现", "",
              "本轮描述这批 PR 在固定检索配置和三个候选预算下的表现，不预设合格线或选定最佳 k。",
              "没有随机或其他方法对照，因此结果本身不构成相对其他方法的优势证据。",
              "候选来自源码定义清单，并非完整 pytest 动态收集。无模型调用、摘要生成或测试执行。",
              "配置、输入及实现哈希见 manifest.json；封存排名见 predictions-manifest.json；",
              "逐 PR 宿主机评价见 evaluation/；机器可读汇总见 summary.json 和 per-pr.csv。", "",
              "```bash", f"python3 -m experiment.bm25_localization --output-dir output/bm25-localization/<new-run-id>",
              "```", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


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
    implementation_files = [Path(__file__), *(Path(sys.modules[obj.__module__].__file__)
                            for obj in (BatchError, testcase_inventory, build_labels))]
    manifest = {
        "version": VERSION, "state": "RANKING", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "inventory": {"path": str(inventory_path.resolve()), "sha256": sha256_file(inventory_path)},
        "raw": {"path": str(raw_path.resolve()), "sha256": raw_sha},
        "parameters": PARAMETERS, "cutoffs": list(CUTOFFS), "tokenizer": TOKENIZER_VERSION,
        "query": "raw title + two newlines + raw body; whitelist only",
        "document": "base path + qualified_name + full source including decorators",
        "idf": "log(1 + (N-df+0.5)/(df+0.5))", "query_term_frequency": "count duplicates",
        "ties": "score descending, source identity ascending", "zero_scores": "included",
        "bm25_reference": BM25_REFERENCE, "pr_count": len(prs), "python": sys.version,
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
    sealed = {"version": VERSION, "document_type": "BM25_PREDICTIONS_SEAL", "predictions": seals,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=BENCH / "batch/inventories/scrapy-pr-inventory.json")
    parser.add_argument("--raw-prs", type=Path, default=ROOT / "output/raw_prs/scrapy__scrapy.jsonl")
    parser.add_argument("--bench", type=Path, default=BENCH)
    run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S%z")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/bm25-localization" / run_id)
    args = parser.parse_args()
    try:
        summary = run_experiment(inventory_path=args.inventory, raw_path=args.raw_prs,
                                 bench=args.bench, output=args.output_dir)
    except (BatchError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"error": error_info(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output_dir.resolve()), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
