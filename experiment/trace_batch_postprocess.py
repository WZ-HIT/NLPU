"""Host-only follow-up: wait for a base batch, analyze and independently check it."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def independent_check(analysis, retrieval_run):
    """Recompute full-coverage pair counts via function->test inverted indexes.

    This deliberately does not call the analysis pair enumeration or its
    feature helpers. Frozen source inventories and forward indexes suffice.
    """
    summary = read(analysis / "summary.json")
    seal = read(analysis / "analysis-manifest.json")
    for name, checksum in seal["files"].items():
        if sha(analysis / name) != checksum:
            raise ValueError("Saved analysis file changed: " + name)
    cache, checked = {}, []
    for reference in summary["analyses"]:
        base = reference["base_sha"]
        if base not in cache:
            bundle = Path(summary["input_trace_manifests"][base]["path"]).parent
            index = read(bundle / "index.json")
            forward = read(bundle / "indexes/test-to-production.json")
            corpus = read(retrieval_run / "corpora" / (base + ".json"))
            candidates = {r["id"] for r in corpus["entries"]}
            cache[base] = index, forward, candidates
        index, forward, candidates = cache[base]
        result = read(analysis / reference["path"])
        allowed = {"complete"} if reference["cohort"] == "complete_only" else {"complete", "partial"}
        ids = sorted(r["id"] for r in index["tests"] if r["coverage_status"] in allowed and r["id"] in candidates)
        positions = {t: i for i, t in enumerate(ids)}
        label = read(retrieval_run / "evaluation" / f"pr-{reference['pr_id']}-labels.json")
        gold = set(label["testcases"]) & set(ids)
        if sorted(gold) != result["updated_ids"]:
            raise ValueError("Updated identity mismatch")
        gold_mask = sum(1 << positions[t] for t in gold)
        posts = defaultdict(int)
        for identity in ids:
            if forward[identity] is None:
                raise ValueError("Unknown coverage entered the pair denominator")
            for symbol in forward[identity]:
                posts[symbol] |= 1 << positions[identity]
        degree, both_degree, one = 0, 0, 0
        for identity in ids:
            neighbors = 0
            for symbol in forward[identity]:
                neighbors |= posts[symbol]
            neighbors &= ~(1 << positions[identity])
            degree += neighbors.bit_count()
            if identity in gold:
                both_degree += (neighbors & gold_mask).bit_count()
                one += (neighbors & ~gold_mask).bit_count()
        both, pairs = both_degree // 2, degree // 2
        expected = {"both_updated": both, "one_updated": one,
                    "neither_updated": pairs - both - one, "pairs": pairs}
        saved = result["tables"]["all_coverage:shared"]
        if any(saved[k] != v for k, v in expected.items()):
            raise ValueError("Independent pair count mismatch")
        total = len(ids) * (len(ids) - 1) // 2
        if result["tables"]["all_pairs"]["pairs"] != total:
            raise ValueError("All-pair denominator mismatch")
        for metric in ("all_coverage", "reachable", "depth_le_1", "depth_le_2", "depth_le_3", "depth_le_5", "depth_ge_4", "root_unreachable", "rare_5pct"):
            a, b = (result["tables"][metric + ":" + x] for x in ("shared", "not_shared"))
            for key in ("both_updated", "one_updated", "neither_updated", "pairs"):
                if a[key] + b[key] != result["tables"]["all_pairs"][key]:
                    raise ValueError("Feature partition does not preserve denominator")
        checked.append({"pr_id": reference["pr_id"], "base_sha": base, "cohort": reference["cohort"],
                        "methods": len(ids), "pairs": total, "shared_cells": expected})
    return {"status": "PASS", "cohorts_checked": len(checked), "bases": len(cache),
            "scope": "independent full-coverage shared-pair counts and identities; all feature partition denominators; result seals",
            "checks": checked}


def findings(analysis, verification):
    summary = read(analysis / "summary.json")
    lines = ["# 全 base 覆盖与共同修改分析", "",
             f"固定范围：{summary['selected_prs']} 个 PR、{summary['selected_bases']} 个 base；本次有冻结证据的 base {summary['trace_bases']} 个，已分析 PR {summary['analyzed_prs']} 个。",
             "全部结果为宿主侧回顾性统计，未观察修改不代表确认不需要修改。未知覆盖不按空集合处理；complete-only 为主分析，包含 partial 的结果单列。", "",
             "| cohort | 共享条件 | 共同更新对中共享比例（等权 PR 宏平均） | 可估计 PR 数 | 已更新种子的共享伙伴更新比例（等权 PR 宏平均） | 可估计 PR 数 |",
             "|---|---|---:|---:|---:|---:|"]
    def percent(value):
        return f"{value:.4%}" if value is not None else "不可估计"
    for cohort, aggregate in summary["aggregate"].items():
        for key in ("all_coverage", "depth_le_1", "depth_le_2", "depth_le_3", "root_unreachable", "rare_5pct"):
            row = aggregate["metrics"][key]
            lines.append(f"| {cohort} | {key} | {percent(row['macro_fraction_updated_pairs_sharing'])} | {row['macro_fraction_denominator_prs']} | {percent(row['macro_partner_update_rate_given_shared_updated_seed'])} | {row['macro_partner_denominator_prs']} |")
    ledger = read(analysis / "base-pr-ledger.json")
    covered_labels = sum(sum(v for k, v in r.get("updated_trace_status", {}).items() if k in {"complete", "partial"}) for r in ledger)
    complete_labels = sum(r.get("updated_trace_status", {}).get("complete", 0) for r in ledger)
    all_labels = sum(r["updated_methods"] for r in ledger)
    lines += ["", f"标签可观测性：共 {all_labels} 个 PR 内更新方法记录，其中 {complete_labels} 个具有完整覆盖、{covered_labels} 个至少具有部分有效覆盖。相同源码方法出现在不同 PR 时按不同任务记录，不跨版本混为一个图。",
              "", "宏平均给每个可估计 PR 相同权重；合并测试对计数另存 summary.json，不能把大量相关测试对当作独立样本。位置分层和保持源码 owner 更新数量的随机对照保存在逐 PR JSON；本摘要不将未经控制的相关性解释为因果或独立预测收益。",
              "", f"独立检查 {verification['cohorts_checked']} 份 PR/cohort 表通过：用倒排索引重新计算共享覆盖测试对与修改身份，核对所有层级分组的分母及文件封存。逐函数层级机制与抽样算法另由单元测试验证。",
              "", "[完整逐 PR 报告](report.md) · [统计汇总与输入证据](summary.json) · [base/PR 可用性台账](base-pr-ledger.csv)", ""]
    (analysis / "findings.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--retrieval-run", required=True, type=Path)
    parser.add_argument("--verify-analysis", type=Path)
    args = parser.parse_args()
    root = args.batch.resolve()
    if args.verify_analysis:
        print(json.dumps(independent_check(args.verify_analysis.resolve(), args.retrieval_run.resolve())))
        return
    state_path = root / "analysis-status.json"
    def state(value):
        state_path.write_text(json.dumps({"updated_at": time.time(), **value}, indent=2) + "\n")
    try:
        state({"status": "WAITING_FOR_COLLECTION"})
        while not (root / "completion.json").exists():
            time.sleep(30)
        completion = read(root / "completion.json")
        sources = read(root / "dynamic-trace-artifacts.json")["artifacts"]
        analysis = root / "analysis"
        command = [sys.executable, "-m", "experiment.trace_cochange", "--retrieval-run", str(args.retrieval_run.resolve()),
                   "--output", str(analysis), "--permutations", "10000"]
        for base, source in sorted(sources.items()):
            manifest = Path(source["path"])
            if sha(manifest) != source["sha256"]:
                raise ValueError("Batch bundle seal changed")
            command += ["--trace-bundle", str(manifest.parent)]
        state({"status": "ANALYZING", "trace_bases": len(sources), "command": command})
        with (root / "audit/analysis.log").open("wb") as log:
            subprocess.run(command, cwd=Path(__file__).resolve().parent, stdout=log, stderr=subprocess.STDOUT, check=True)
        state({"status": "VERIFYING"})
        verification = independent_check(analysis, args.retrieval_run.resolve())
        (root / "audit/analysis-verification.json").write_text(json.dumps(verification, indent=2) + "\n")
        findings(analysis, verification)
        state({"status": "COMPLETE" if completion["all_bases_sealed"] else "COMPLETE_WITH_MISSING_BASES",
               "report": str(analysis / "findings.md"), "verification": "PASS", "trace_bases": len(sources)})
    except Exception as exc:
        state({"status": "FAILED", "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
