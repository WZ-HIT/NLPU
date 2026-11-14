"""Host-only sharing between recalled and missed gold tests in frozen A/B/C runs.

Reads saved predictions, labels and base traces; never executes tests or models.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from pathlib import Path
import statistics

from experiment.trace_cochange import method_depths, write_json
from test_trace.common import digest, file_hash, read_json
from test_trace.query import safe_file

METRICS = ("all_coverage", "depth_le_3", "depth_le_2", "depth_le_1")
COHORTS = {"complete_only": {"complete"},
           "available_including_partial": {"complete", "partial"}}


def functions(record, metric):
    if metric == "all_coverage":
        return record["coverage"]
    limit = int(metric.rsplit("_", 1)[1])
    return {f for f, depth in record["depths"].items() if depth <= limit}


def sharing(missed, recalled, records, allowed):
    """Count each missed method once; retain a concrete seed/function witness."""
    seeds = sorted(t for t in recalled if records[t]["coverage_status"] in allowed)
    rows = []
    for test in sorted(missed):
        record = records[test]
        eligible = record["coverage_status"] in allowed and bool(seeds)
        evidence = {}
        for metric in METRICS:
            witnesses = []
            if eligible:
                own = functions(record, metric)
                for seed in seeds:
                    shared = sorted(own & functions(records[seed], metric))
                    if shared:
                        f = shared[0]
                        witnesses.append({"recalled_test": seed, "function": f,
                                          "missed_depth": record["depths"].get(f),
                                          "recalled_depth": records[seed]["depths"].get(f)})
            # Only complete evidence at every endpoint permits a negative claim.
            resolved_negative = (record["coverage_status"] == "complete" and
                                 bool(recalled) and all(records[t]["coverage_status"] == "complete"
                                                        for t in recalled))
            evidence[metric] = {"shared": bool(witnesses),
                                "state": "shared" if witnesses else
                                ("not_shared" if resolved_negative else "unknown"),
                                "witnesses": witnesses}
        flags = [evidence[m]["shared"] for m in METRICS]
        if any(flags[i + 1] and not flags[i] for i in range(3)):
            raise ValueError("Sharing layer nesting violated")
        rows.append({"missed_test": test, "coverage_status": record["coverage_status"],
                     "eligible": eligible, "metrics": evidence})
    return {"recalled_trace_status": dict(Counter(records[t]["coverage_status"] for t in recalled)),
            "missed_trace_status": dict(Counter(records[t]["coverage_status"] for t in missed)),
            "eligible_recalled": len(seeds), "eligible_missed": sum(r["eligible"] for r in rows),
            "missed": rows}


def summarize(rows):
    partial = [r for r in rows if r["recall_state"] == "partial"]
    total = sum(r["fn"] for r in partial)
    eligible = sum(r["sharing"]["eligible_missed"] for r in partial)
    result = {"tasks": len(rows), "recall_states": dict(Counter(r["recall_state"] for r in rows)),
              "partial_tasks": len(partial), "partial_unique_prs": len({r["pr_id"] for r in partial}),
              "partial_pr_ids": sorted({r["pr_id"] for r in partial}),
              "missed_total": total, "eligible_missed": eligible,
              "missed_trace_status": dict(sum((Counter(r["sharing"]["missed_trace_status"])
                                                for r in partial), Counter())), "metrics": {}}
    for metric in METRICS:
        hits = sum(sum(m["metrics"][metric]["shared"] for m in r["sharing"]["missed"]) for r in partial)
        unknown = sum(sum(m["metrics"][metric]["state"] == "unknown" for m in r["sharing"]["missed"])
                      for r in partial)
        result["metrics"][metric] = {
            "shared_missed": hits, "fraction_all_missed": hits / total if total else None,
            "fraction_eligible_missed": hits / eligible if eligible else None,
            "unknown_missed": unknown, "confirmed_not_shared": total - hits - unknown,
            "tasks_with_shared_missed": sum(any(m["metrics"][metric]["shared"]
                                                 for m in r["sharing"]["missed"]) for r in partial),
            "macro_fraction_all_missed": statistics.mean(
                sum(m["metrics"][metric]["shared"] for m in r["sharing"]["missed"]) / r["fn"]
                for r in partial) if partial else None}
    return result


def verify_pair_counts(rows, analysis_root, manifest, checked):
    """Independent count path: use previously verified exhaustive pair CSVs."""
    cache = {}
    checks = 0
    for row in rows:
        if row["recall_state"] != "partial":
            continue
        key = row["base_sha"], row["pr_id"], row["cohort"]
        if key not in cache:
            base, pr, cohort = key
            relative = f"per-base/{base}/pr-{pr}-{cohort}-updated-pairs.csv"
            path = analysis_root / relative
            checksum = file_hash(path)
            if checksum != manifest["files"][relative]:
                raise ValueError("Frozen exhaustive pair CSV changed")
            # CSV input cannot use the JSON reader.
            checked[str(path)] = checksum
            with path.open(newline="", encoding="utf-8") as f:
                cache[key] = list(csv.DictReader(f))
        seeds = set(row["recalled_tests"])
        missed = {m["missed_test"] for m in row["sharing"]["missed"]}
        for metric in METRICS:
            expected = set()
            for pair in cache[key]:
                if int(pair[metric]):
                    a, b = pair["test_a"], pair["test_b"]
                    if a in seeds and b in missed:
                        expected.add(b)
                    if b in seeds and a in missed:
                        expected.add(a)
            actual = {m["missed_test"] for m in row["sharing"]["missed"] if m["metrics"][metric]["shared"]}
            if actual != expected:
                raise ValueError("Independent exhaustive-pair sharing check differs")
            checks += 1
    return {"status": "PASS", "metric_task_cohort_checks": checks,
            "independent_pair_csvs": len(cache), "method": "exact missed-identity set equality against sealed exhaustive pair CSVs"}


def run(comparison_path, trace_batch, output):
    if output.exists():
        raise ValueError("Use a new output directory")
    comparison = read_json(comparison_path)
    inputs = {str(comparison_path): file_hash(comparison_path)}

    def checked(path, checksum=None):
        path = Path(path)
        actual = file_hash(path)
        if checksum is not None and actual != checksum:
            raise ValueError("Changed frozen input: " + str(path))
        inputs[str(path)] = actual
        return read_json(path)

    adoc = checked(comparison["sources"]["A"]["path"], comparison["sources"]["A"]["sha256"])
    bcdoc = checked(comparison["sources"]["BC"]["path"], comparison["sources"]["BC"]["sha256"])
    groups = {"A": adoc["direct_history"]["rows"],
              **{g: bcdoc["groups"][g]["rows"] for g in ("B", "C")}}
    keys = {(r["task_id"], r["method"]) for r in groups["A"]}
    if any(len(rows) != len(keys) or {(r["task_id"], r["method"]) for r in rows} != keys
           for rows in groups.values()):
        raise ValueError("A/B/C task identities differ")
    analysis_root = trace_batch / "analysis-full-v2"
    analysis_manifest = checked(analysis_root / "analysis-manifest.json")
    summary = checked(analysis_root / "summary.json", analysis_manifest["files"]["summary.json"])
    per_pr_path = next(p for p in summary["input_source_files"] if p.endswith("/per-pr.json"))
    per_pr = checked(per_pr_path, summary["input_source_files"][per_pr_path])
    lookup = {r["pr_id"]: r for r in per_pr}
    artifacts = checked(trace_batch / "dynamic-trace-artifacts.json")["artifacts"]
    labels, traces, bundles = {}, {}, {}
    task_ids = sorted({k[0] for k in keys})
    for task in task_ids:
        pr = int(task.rsplit("pr", 1)[1]); source = lookup[pr]; base = source["base_sha"]
        lp = Path(per_pr_path).parent / "evaluation" / f"pr-{pr}-labels.json"
        label = checked(lp, summary["input_source_files"][str(lp)])
        if (not label["complete"] or label["base_sha"] != base or
                label["labels_sha256"] != source["labels_sha256"] or
                digest({k: v for k, v in label.items() if k != "labels_sha256"}) != label["labels_sha256"]):
            raise ValueError("Label seal/base mismatch")
        labels[task] = label
        if base not in bundles:
            ref = artifacts[base]
            if ref != summary["input_trace_manifests"][base]:
                raise ValueError("Trace manifest differs from verified analysis")
            mp = Path(ref["path"]); manifest = checked(mp, ref["sha256"])
            index = checked(mp.parent / "index.json", manifest["files"]["index.json"])
            if index["base_sha"] != base or manifest["base_sha"] != base:
                raise ValueError("Trace base mismatch")
            corpus_path = Path(per_pr_path).parent / "corpora" / f"{base}.json"
            corpus = checked(corpus_path, summary["input_source_files"][str(corpus_path)])
            if corpus["index_sha256"] != label["index_sha256"]:
                raise ValueError("Candidate index differs from label index")
            if any(manifest["source_files"].get(e["path"]) != e["file_sha256"] for e in corpus["entries"]):
                raise ValueError("Trace source differs from frozen candidate source")
            bundles[base] = mp.parent, manifest, {e["id"]: e for e in index["tests"]}
        root, manifest, entries = bundles[base]
        for identity in label["testcases"]:
            key = base, identity
            if key in traces:
                continue
            if identity not in entries:
                traces[key] = {"coverage_status": "not_discovered", "coverage": set(), "depths": {}}
                continue
            e = entries[identity]
            d = checked(safe_file(root, e["path"]), manifest["files"][e["path"]])
            if d["source_test_id"] != identity or d["coverage_status"] != e["coverage_status"]:
                raise ValueError("Trace source identity/status mismatch")
            coverage = d["production_covered_functions"]
            if (coverage is None) != (e["coverage_status"] == "unavailable"):
                raise ValueError("Unknown coverage status inconsistent")
            traces[key] = {"coverage_status": e["coverage_status"], "coverage": set(coverage or []),
                           "depths": method_depths(d) if coverage is not None else {}}
    print(f"Verified {len(task_ids)} PRs, {len(bundles)} bases, {len(traces)} gold-method traces", flush=True)
    rows = []
    for group, predictions in groups.items():
        sums = Counter()
        for r in predictions:
            label = labels[r["task_id"]]; gold = set(label["testcases"])
            if (r["index_sha256"], r["labels_sha256"]) != (label["index_sha256"], label["labels_sha256"]):
                raise ValueError("Prediction label/index mismatch")
            pred = set(r["prediction"]["testcases"])
            recalled, missed = pred & gold, gold - pred
            tp, fn = len(recalled), len(missed)
            if gold and (r["testcase"]["tp"], r["testcase"]["fn"]) != (tp, fn):
                raise ValueError("Independent recall counts differ")
            sums.update(tp=tp, fn=fn)
            state = "no_gold" if not gold else "zero" if not tp else "partial" if fn else "full"
            records = {t: traces[label["base_sha"], t] for t in gold}
            for cohort, allowed in COHORTS.items():
                rows.append({"group": group, "cohort": cohort, "task_id": r["task_id"],
                             "pr_id": int(r["task_id"].rsplit("pr", 1)[1]), "method": r["method"],
                             "base_sha": label["base_sha"], "run_status": r["status"],
                             "recall_state": state, "gold_count": len(gold), "tp": tp, "fn": fn,
                             "recalled_tests": sorted(recalled),
                             "sharing": sharing(missed, recalled, records, allowed) if state == "partial" else None})
        if any(sums[k] != comparison["groups"][group]["counts"][k] for k in ("tp", "fn")):
            raise ValueError("Aggregate recall counts differ from original A/B/C comparison")
    verification = verify_pair_counts(rows, analysis_root, analysis_manifest, inputs)
    aggregates = {cohort: {g: {"all_sdd": summarize([r for r in rows if r["cohort"] == cohort and r["group"] == g]),
                              "per_sdd": {m: summarize([r for r in rows if r["cohort"] == cohort and r["group"] == g and r["method"] == m])
                                          for m in ("openspec", "speckit", "cc-sdd")}}
                            for g in groups} for cohort in COHORTS}
    output.mkdir(parents=True)
    result = {"version": "trace-recall-gaps-v1", "scope": "HOST_ONLY_RETROSPECTIVE",
              "groups": {"A": "historical direct localization", "B": "static facts", "C": "static facts and semantic intention"},
              "protocol": {"selection": "0 < TP < gold count, separately within each PR x SDD",
                           "seeds": "correctly recalled gold test methods only; false positives excluded",
                           "unit": "each missed source method counted once per PR x SDD",
                           "depth": "same production function within k edges of each root; per-valid-instance BFS then minimum",
                           "primary": "complete_only", "sensitivity": "available_including_partial",
                           "denominator_all": "all missed targets within partial-recall tasks; observed-sharing lower bound",
                           "denominator_eligible": "missed trace allowed and at least one recalled trace allowed",
                           "unknown": "no positive witness with incomplete endpoint evidence is unknown, never a confirmed nonshare",
                           "new_models_or_test_executions": 0}, "aggregates": aggregates, "rows": rows,
              "input_files": inputs, "verification": verification}
    write_json(output / "results.json", result)
    write_json(output / "verification.json", verification)
    fields = ["group", "cohort", "method", "pr_id", "base_sha", "recall_state", "tp", "fn", "eligible_recalled", "eligible_missed", *METRICS]
    with (output / "per-pr-sdd.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fields); writer.writeheader()
        for r in rows:
            share = r["sharing"]
            writer.writerow({**{k: r[k] for k in fields if k in r},
                             "eligible_recalled": share["eligible_recalled"] if share else None,
                             "eligible_missed": share["eligible_missed"] if share else None,
                             **{m: sum(x["metrics"][m]["shared"] for x in share["missed"]) if share else None for m in METRICS}})
    render(output, result)
    write_json(output / "manifest.json", {"files": {p.name: file_hash(p) for p in output.iterdir() if p.is_file()},
                                          "implementation": {str(Path(__file__).resolve()): file_hash(Path(__file__))},
                                          "input_files": inputs})
    return result


def render(output, result):
    lines = ["# A/B/C 部分召回任务中漏召回测试的覆盖共享", "",
             "范围：原 A/B/C 的相同 30 PR × 3 SDD；A 为历史组。只读既有预测、宿主标签及 base 动态轨迹，没有新模型调用或测试执行。",
             "仅统计 0 < TP < gold_count 的 PR×SDD；三种 SDD 不合并预测。以正确召回目标为种子，误报不作种子。每个漏召回方法满足至少一个种子的共享条件即计一次。",
             "层级要求同一共享生产函数在双方都位于 k 层以内；层数从测试根沿直接调用边计算。任意共享不限层级，也可包含被覆盖但因外部边界不可从根到达的函数。", ""]
    for cohort, groups in result["aggregates"].items():
        lines += [f"## {cohort}", "", "| 组 | 部分召回任务/独立PR | 漏召回数 | 可比较漏召回数 | 任意共享 | 三层内 | 两层内 | 一层内 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for g, d in groups.items():
            s = d["all_sdd"]
            cells = [f"{s['metrics'][m]['shared_missed']} ({s['metrics'][m]['fraction_all_missed']:.2%})" if s["missed_total"] else "—" for m in METRICS]
            lines.append(f"| {g} | {s['partial_tasks']}/{s['partial_unique_prs']} | {s['missed_total']} | {s['eligible_missed']} | " + " | ".join(cells) + " |")
        lines += ["", "括号分母为部分召回任务的全部漏召回目标。证据不全时这是已证实共享比例的下界，不把未知当作确认不共享。", "",
                  "| 组 | SDD | 部分召回任务 | 漏召回数 | 可比较数 | 任意共享 | 三层内 | 两层内 | 一层内 |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for g, d in groups.items():
            for m, s in d["per_sdd"].items():
                cells = [f"{s['metrics'][k]['shared_missed']} ({s['metrics'][k]['fraction_all_missed']:.2%})" if s["missed_total"] else "—" for k in METRICS]
                lines.append(f"| {g} | {m} | {s['partial_tasks']} | {s['missed_total']} | {s['eligible_missed']} | " + " | ".join(cells) + " |")
        lines += ["", "### 限可比较漏召回目标的比例", "", "| 组 | 任意共享 | 三层内 | 两层内 | 一层内 |", "|---|---:|---:|---:|---:|"]
        for g, d in groups.items():
            s = d["all_sdd"]
            cells = [f"{s['metrics'][m]['fraction_eligible_missed']:.2%}" if s["eligible_missed"] else "—" for m in METRICS]
            lines.append(f"| {g} | " + " | ".join(cells) + " |")
        lines += [""]
        lines += ["### 各部分召回任务等权平均（Macro）", "", "| 组 | 任意共享 | 三层内 | 两层内 | 一层内 |", "|---|---:|---:|---:|---:|"]
        for g, d in groups.items():
            s = d["all_sdd"]
            cells = [f"{s['metrics'][m]['macro_fraction_all_missed']:.2%}" if s["partial_tasks"] else "—" for m in METRICS]
            lines.append(f"| {g} | " + " | ".join(cells) + " |")
        lines += ["", "该表先在每个部分召回 PR×SDD 内计算共享漏召回数/FN，再等权平均；不是前面合并计数的比例，也不是独立样本显著性检验。", ""]
    lines += ["## 漏召回目标的 PR 分布", "", "| 组 | 部分召回任务中的 PR | 漏召回数（跨 SDD 计次） | 占本组部分召回漏召回数 |", "|---|---:|---:|---:|"]
    for g in result["groups"]:
        counts = Counter()
        for row in result["rows"]:
            if row["group"] == g and row["cohort"] == "complete_only" and row["recall_state"] == "partial":
                counts[row["pr_id"]] += row["fn"]
        total = sum(counts.values())
        for pr, count in counts.most_common():
            lines.append(f"| {g} | {pr} | {count} | {count / total:.2%} |")
    lines += [""]
    lines += ["## 阅读边界", "", "- 合计按 PR×SDD×漏召回方法计数，同一 PR 的方法可在不同 SDD 重复出现，不是互不重复的测试数。",
              "- 主表 complete_only 只用两端均完整的证据建立共享关系；partial 敏感性表可新增已观测正关系，但不证明完整覆盖。",
              "- 不同组的部分召回任务集合不同，组间比例不能直接当作方法优劣比较。零召回、全召回、无正例任务均未进入主分母。",
              "- 此分析用标签区分 TP/FN，是回顾性关联分析。它不提供真实扩展策略的 precision，也不证明所有关联候选都需要更新。",
              "- results.json 保存全部逐漏召回方法记录、种子与共享函数证据、两侧层级、未知状态、macro 比例及输入哈希；per-pr-sdd.csv 保存全部任务行。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--trace-batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.comparison.resolve(), args.trace_batch.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
