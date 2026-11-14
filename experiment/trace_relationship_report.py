"""Interpret completed host trace analysis, preserving PR and base denominators."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import random
import statistics

from test_trace.common import file_hash, read_json, write_json


def cluster_mean(rows, *, draws=5000, seed=42):
    """Equal-PR mean; resample whole base clusters, retaining all their PRs."""
    groups = defaultdict(list)
    for base, value in rows:
        groups[base].append(value)
    result = {"mean": statistics.mean(v for _, v in rows) if rows else None,
              "n_prs": len(rows), "n_bases": len(groups), "low": None, "high": None}
    if len(groups) < 2:
        return result
    totals = [(sum(values), len(values)) for _, values in sorted(groups.items())]
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        selected = rng.choices(totals, k=len(totals))
        samples.append(sum(s for s, _ in selected) / sum(n for _, n in selected))
    samples.sort()
    result.update(low=samples[int(.025 * (draws - 1))], high=samples[int(.975 * (draws - 1))])
    return result


def pct(value):
    return "不可估计" if value is None else f"{value:.2%}"


def pp(value):
    return "不可估计" if value is None else f"{100 * value:+.2f}"


def run(analysis, batch, output):
    if output.exists():
        raise ValueError("Use a new reviewed report directory")
    output.mkdir(parents=True)
    summary = read_json(analysis / "summary.json")
    verification = read_json(analysis / "verification.json")
    if verification["status"] != "PASS":
        raise ValueError("Full analysis must pass independent checks first")
    refs = summary["analyses"]
    records = [read_json(analysis / ref["path"]) for ref in refs]
    completion = read_json(batch / "completion.json")
    outcomes, evidence, method_status = Counter(), Counter(), Counter()
    for job in completion["jobs"]:
        outcomes.update(job["summary"]["outcomes"])
        evidence.update(job["summary"]["evidence"])
        method_status.update(job["summary"]["method_coverage_status"])
    ledger = read_json(analysis / "base-pr-ledger.json")
    label_status = Counter()
    for row in ledger:
        label_status.update(row["updated_trace_status"])
    label_total = sum(label_status.values())
    execution_total = sum(outcomes.values())
    method_total = sum(method_status.values())
    all_metrics, cohort_results = [], {}
    for cohort in ("complete_only", "available_including_partial"):
        selected = [r for r in records if r["cohort"] == cohort]
        multi = [r for r in selected if r["updated_methods"] >= 2]
        metrics = {}
        for key in ("all_coverage", "reachable", "depth_le_1", "depth_le_2", "depth_le_3", "depth_le_5", "depth_ge_4", "root_unreachable", "rare_5pct"):
            forward, matched_diff, partner, paired_diff = [], [], [], []
            uniform, owner = [], []
            for r in multi:
                den = r["tables"]["all_pairs"]["both_updated"]
                obs = r["tables"][key + ":shared"]["both_updated"] / den
                permutation = r["permutation"]["results"]
                null = permutation["source_owner_matched"][key]["null_mean_shared_pairs"] / den
                forward.append((r["base_sha"], obs)); matched_diff.append((r["base_sha"], obs - null))
                uniform.append(permutation["uniform"][key]["null_mean_shared_pairs"] / den); owner.append(null)
            for r in selected:
                shared = r["tables"][key + ":shared"]["p_partner_updated_given_updated_seed"]
                absent = r["tables"][key + ":not_shared"]["p_partner_updated_given_updated_seed"]
                if shared is not None:
                    partner.append((r["base_sha"], shared))
                if shared is not None and absent is not None:
                    paired_diff.append((r["base_sha"], shared - absent))
            metrics[key] = {"forward": cluster_mean(forward), "uniform_expected": statistics.mean(uniform) if uniform else None,
                            "owner_expected": statistics.mean(owner) if owner else None,
                            "owner_adjusted_difference": cluster_mean(matched_diff),
                            "partner": cluster_mean(partner), "shared_vs_absent_paired_difference": cluster_mean(paired_diff)}
            all_metrics.append({"cohort": cohort, "condition": key, "forward": metrics[key]["forward"]["mean"],
                                "forward_prs": len(multi), "partner": metrics[key]["partner"]["mean"],
                                "partner_prs": len(partner), "owner_expected": metrics[key]["owner_expected"],
                                "owner_adjusted_difference": metrics[key]["owner_adjusted_difference"]["mean"],
                                "owner_adjusted_low": metrics[key]["owner_adjusted_difference"]["low"],
                                "owner_adjusted_high": metrics[key]["owner_adjusted_difference"]["high"]})
        aligned_keys = ("all_coverage", "depth_le_1", "depth_le_2", "rare_5pct")
        aligned = [r for r in selected if all(r["tables"][key + ":shared"]["p_partner_updated_given_updated_seed"] is not None for key in aligned_keys)]
        aligned_rates = {key: cluster_mean([(r["base_sha"], r["tables"][key + ":shared"]["p_partner_updated_given_updated_seed"]) for r in aligned]) for key in aligned_keys}
        aligned_rates["random_partner"] = cluster_mean([(r["base_sha"], r["random_partner_update_rate"]) for r in aligned])
        equal_rows, equality_count, positive_pairs = [], 0, 0
        for ref, record in zip(refs, records):
            if record["cohort"] != cohort:
                continue
            csv_path = (analysis / ref["path"]).parent / record["all_updated_pair_counts_csv"]
            pairs, equal = 0, 0
            with csv_path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    pairs += 1
                    equal += int(int(row["shared_count"]) > 0 and int(row["shared_count"]) == int(row["coverage_a"]) == int(row["coverage_b"]))
            if pairs != record["updated_pair_count"]:
                raise ValueError("All updated-pair CSV count mismatch")
            positive_pairs += pairs; equality_count += equal
            if pairs:
                equal_rows.append((record["base_sha"], equal / pairs))
        cohort_results[cohort] = {"metrics": metrics, "aligned_partner": aligned_rates,
                                 "eligible_updated_records": sum(r["updated_methods"] for r in selected),
                                 "multi_updated_prs": len(multi), "all_updated_pairs": positive_pairs,
                                 "identical_nonempty_coverage_updated_pairs": equality_count,
                                 "macro_identical_coverage_pair_fraction": cluster_mean(equal_rows),
                                 "median_partner_rate_all_coverage": statistics.median(v for _, v in [(r['base_sha'], r['tables']['all_coverage:shared']['p_partner_updated_given_updated_seed']) for r in selected] if v is not None)}
    result = {"scope": {"prs": summary["selected_prs"], "bases": summary["trace_bases"], "label_records": sum(label_status.values()),
                         "label_coverage_status": dict(label_status), "outcomes": dict(outcomes), "evidence": dict(evidence),
                         "method_status_by_base": dict(method_status)},
              "cohorts": cohort_results, "bootstrap": {"unit": "base cluster", "draws": 5000, "seed": 42, "interval": "percentile 95%", "weight": "equal PR"},
              "inputs": {"summary": {"path": str(analysis / "summary.json"), "sha256": file_hash(analysis / "summary.json")},
                         "verification": {"path": str(analysis / "verification.json"), "sha256": file_hash(analysis / "verification.json")}}}
    write_json(output / "results.json", result)
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_metrics[0])); writer.writeheader(); writer.writerows(all_metrics)
    primary = cohort_results["complete_only"]
    metrics = primary["metrics"]
    lines = ["# 98 个 PR 的覆盖共享、调用层级与共同修改", "",
             f"`REUSED_VERIFIED` 表示复用并重新校验已有封存包，保留原始运行来源；不表示本批次重跑，也不表示所有测试通过。本次 {summary['trace_bases']} 个 base 中 {completion['status_counts'].get('SEALED', 0)} 个新采集、{completion['status_counts'].get('REUSED_VERIFIED', 0)} 个复用，全部已封存。", "",
             "## 数据范围与可观测性", "",
             f"{summary['selected_prs']} 个 PR 对应 {summary['trace_bases']} 个 base，{execution_total:,} 个执行实例都有终态记录，{evidence['valid']:,} 条轨迹有效。按 base 分别统计源码方法共 {method_total:,} 条，其中完整覆盖 {method_status['complete']:,}、部分覆盖 {method_status['partial']:,}、不可用 {method_status['unavailable']:,}；这不是跨版本去重后的测试数量。",
             f"{label_total:,} 个 PR 内更新方法记录中，完整覆盖 {label_status['complete']}（{label_status['complete']/label_total:.2%}），部分覆盖 {label_status['partial']}，不可用 {label_status['unavailable']}，未发现 {label_status['not_discovered']}。未知覆盖未填成空集合。",
             f"主分析仅使用完整覆盖：{primary['multi_updated_prs']} 个 PR 能形成至少一对共同修改测试，共 {primary['all_updated_pairs']:,} 对。单更新、无已有更新标签、或覆盖不足的 PR 不能估计共同修改对的比例，仍保留在台账。含部分覆盖的敏感性分析有 {cohort_results['available_including_partial']['multi_updated_prs']} 个可估计 PR。", "",
             "## 问题一：共同修改的测试是否共享生产函数？", "",
             f"以下为等权 PR 宏平均；各行使用相同的 {primary['multi_updated_prs']} 个可估计 PR。浅层条件要求双方均在该深度以内覆盖同一函数，各条件可重叠，不能相加。", "",
             "| 共享条件 | 共同修改对中的共享比例 | 均匀随机对照 | 保留源码类更新数量的对照 | 超出类对照（百分点） | 按 base 聚类 95% 区间（百分点） |",
             "|---|---:|---:|---:|---:|---:|"]
    for key in ("all_coverage", "depth_le_1", "depth_le_2", "depth_le_3", "depth_le_5", "rare_5pct", "root_unreachable"):
        m = metrics[key]; d = m["owner_adjusted_difference"]
        lines.append(f"| {key} | {pct(m['forward']['mean'])} | {pct(m['uniform_expected'])} | {pct(m['owner_expected'])} | {pp(d['mean'])} | [{pp(d['low'])}, {pp(d['high'])}] |")
    lines += ["", f"共同修改不代表完整覆盖集合相同：主分析中覆盖集合非空且完全相同的更新测试对有 {primary['identical_nonempty_coverage_updated_pairs']:,}/{primary['all_updated_pairs']:,} 对；其等权 PR 宏平均比例为 {pct(primary['macro_identical_coverage_pair_fraction']['mean'])}。", "",
              "类对照采用同文件的实际源码 owner（源码类；顶层函数则为模块），保持每个 owner 内被更新方法的数量；每个 PR 抽样 10,000 次。区间通过整体重采样 base 聚类计算，避免把相关测试对当独立样本。区间仅作稳定性检查，不是因果证明。", "",
              "## 问题二：共享函数的测试是否往往共同修改？", "",
              f"以已观察到修改的测试为种子，共享任意生产函数的伙伴也被修改的宏平均比例为 {pct(metrics['all_coverage']['partner']['mean'])}（{metrics['all_coverage']['partner']['n_prs']} 个可估计 PR）；中位数为 {pct(primary['median_partner_rate_all_coverage'])}。主分析按全部共享无序测试对合并计算，两者都修改的比例为 {summary['aggregate']['complete_only']['metrics']['all_coverage']['pooled_shared_pair_cells']['p_both_observed_updated']:.6%}，与已知一个种子被修改的条件比例不是同一个分母。", "",
              "比较不同共享条件时，下表固定为四个条件都存在可观察伙伴的同一批 PR，消除各条件可估计 PR 数不同的影响。", "",
              "| 条件 | 已修改种子的伙伴也修改的比例 | PR 数 |", "|---|---:|---:|"]
    for key, m in primary["aligned_partner"].items():
        lines.append(f"| {key} | {pct(m['mean'])} | {m['n_prs']} |")
    lines += ["", "低频函数定义固定为：覆盖该函数的候选方法不超过当前候选方法的 5%，与修改标签无关。它能提高共同修改的集中度，但会丢失大量共同修改对，不能直接用作硬过滤。浅层共享同样存在集中度与保留范围的取舍。", "",
              "## 调用层级和研究含义", "",
              "层级是每个有效执行实例中从测试根出发的 BFS 最短距离，再跨该源码方法的实例取最小值；没有把不同实例的边拼成路径。函数图层级不等于最大实际栈深度。root_unreachable 是覆盖已观察到、但因外部/不透明边界无法沿内部边从根连通的函数，不是未覆盖或最深层。",
              "共享任意函数的很多关联已能由测试类归属解释。完整覆盖、浅层覆盖和低频覆盖是不同强度的关联证据；应同时考虑函数普遍度、测试类位置、覆盖相似度及边界可观测性，不能只按一个共享函数就断定需要更新。",
              "这些结果是知道实际修改种子后的回顾性关联，不是 SDD 定位效果。实际方法还需从允许的任务描述/base 预测种子，并验证错误扩散、候选召回、精度和成本；本次未调用模型、未启动新的 SDD 实验。", "",
              "## 敏感性与交付", "",
              f"纳入 partial 后，共同修改对共享任意函数的等权 PR 宏平均为 {pct(cohort_results['available_including_partial']['metrics']['all_coverage']['forward']['mean'])}；完整覆盖主分析为 {pct(metrics['all_coverage']['forward']['mean'])}。结论方向相近，但不可用更新方法仍可能形成选择偏差。未修改只表示当前 PR 未观察到修改，不是确认不需要修改。",
              f"全量输入封存、{verification['cohorts_checked']} 份 PR/cohort 的独立计数重算和完整更新测试对 CSV 已保存于 `{analysis}`。results.json 和 metrics.csv 保存本报告所有数值与聚类区间，未覆盖信息见该目录的 base-pr-ledger.json。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(output / "manifest.json", {"files": {p.name: file_hash(p) for p in output.iterdir() if p.is_file()},
                                          "implementation_sha256": file_hash(Path(__file__)), "inputs": result["inputs"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.analysis.resolve(), args.batch.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
