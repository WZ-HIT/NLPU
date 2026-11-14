"""Host-only retrospective analysis of frozen base traces and test-update labels.

Never import this module from the collector or an SDD Agent input builder.
No test execution, model calls, network access, or trace mutation occurs here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import csv
from itertools import combinations
import json
from pathlib import Path
import random

from test_trace.common import digest, file_hash, read_json
from test_trace.query import safe_file
from test_trace.store import verify

VERSION = "trace-cochange-v1.2"
LAYERS = (1, 2, 3, 5)
METRICS = ("all_coverage", "reachable", *(f"depth_le_{n}" for n in LAYERS),
           "depth_ge_4", "root_unreachable", "rare_5pct")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n", encoding="utf-8")


def bfs(root, edges):
    graph = defaultdict(list)
    for edge in edges:
        graph[edge["caller"]].append(edge["callee"])
    distances = {root: 0}
    queue = deque([root])
    while queue:
        parent = queue.popleft()
        for child in graph[parent]:
            if child not in distances:
                distances[child] = distances[parent] + 1
                queue.append(child)
    return distances


def method_depths(document):
    """Minimum BFS distance over individual valid execution graphs.

    Traversing the union graph could splice edges from different parameter or
    inheritance instances into a path that no individual execution observed.
    Aggregate edge provenance lets us avoid that without reopening diagnostics.
    This still measures a collapsed function graph, not temporal stack depth.
    """
    valid = {r["execution_id"] for r in document["instances"]
             if r["evidence_status"] == "valid"}
    by_instance = {identity: [] for identity in valid}
    for edge in document["edges"]:
        support = edge.get("supporting_instances")
        if not support or not set(support) <= valid:
            raise ValueError("Missing or invalid edge-instance provenance")
        for identity in support:
            by_instance[identity].append(edge)
    minimum = {}
    for edges in by_instance.values():
        for symbol, distance in bfs(document["source_test_id"], edges).items():
            minimum[symbol] = min(distance, minimum.get(symbol, distance))
    production = set(document["production_covered_functions"] or [])
    return {symbol: minimum[symbol] for symbol in production if symbol in minimum}


def location(identity):
    path, qualified = identity.split("::", 1)
    owner = qualified.rsplit(".", 1)[0] if "." in qualified else "<module>"
    return path, owner


def stratum(a, b):
    pa, ca = location(a)
    pb, cb = location(b)
    if pa != pb:
        return "different_file"
    return "same_source_owner" if ca == cb else "same_file_different_owner"


def load_trace(root):
    verification = verify(root)
    index = read_json(root / "index.json")
    methods = {}
    for entry in index["tests"]:
        if entry["id"] in methods:
            raise ValueError("Duplicate source test identity")
        document = read_json(safe_file(root, entry["path"]))
        if document["source_test_id"] != entry["id"]:
            raise ValueError("Method identity mismatch")
        coverage = document["production_covered_functions"]
        if entry["coverage_status"] == "unavailable":
            if coverage is not None:
                raise ValueError("Unavailable coverage must remain unknown")
        else:
            if coverage is None:
                raise ValueError("Available coverage cannot be null")
        depths = method_depths(document) if coverage is not None else {}
        methods[entry["id"]] = {"coverage_status": entry["coverage_status"],
                                "coverage": set(coverage or []), "depths": depths,
                                "expected_instances": entry["expected_instances"],
                                "valid_instances": entry["valid_instances"]}
    return index, methods, verification


def feature_sets(record, rare):
    covered, depths = record["coverage"], record["depths"]
    return {"all_coverage": covered, "reachable": set(depths),
            **{f"depth_le_{n}": {s for s, d in depths.items() if d <= n} for n in LAYERS},
            "depth_ge_4": {s for s, d in depths.items() if d >= 4},
            "root_unreachable": covered - set(depths), "rare_5pct": covered & rare}


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


def summarize_cells(cells):
    """Unordered pair table plus an ordered, updated-seed-conditioned table."""
    both, one, neither = (cells.get(k, 0) for k in ("both_updated", "one_updated", "neither_updated"))
    total = both + one + neither
    return {**{k: cells.get(k, 0) for k in ("both_updated", "one_updated", "neither_updated")},
            "pairs": total, "p_both_observed_updated": rate(both, total),
            "updated_seed_partner_observations": both * 2 + one,
            "p_partner_updated_given_updated_seed": rate(both * 2, both * 2 + one)}


def jaccard_bin(intersection, union):
    if not intersection:
        return "0"
    value = intersection / union
    for upper in (0.1, 0.25, 0.5, 0.75):
        if value < upper:
            return f"lt_{upper}"
    return "ge_0.75"


def pair_analysis(methods, gold, *, permutations=10000, seed=42, pair_sink=None, detail_limit=100):
    ids = sorted(methods)
    gold = set(gold) & set(ids)
    n = len(ids)
    frequency = Counter(symbol for m in methods.values() for symbol in m["coverage"])
    # Corpus-only, fixed cutoff, never adjusted after seeing update labels.
    rare = {s for s, count in frequency.items() if count / n <= 0.05} if n else set()
    symbols = {s: i for i, s in enumerate(sorted(frequency))}
    features = {identity: feature_sets(methods[identity], rare) for identity in ids}
    bits = {key: [sum(1 << symbols[s] for s in features[t][key]) for t in ids] for key in METRICS}
    gold_indices = {i for i, identity in enumerate(ids) if identity in gold}
    records = {"all_pairs": Counter()}
    for key in METRICS:
        records[key + ":shared"] = Counter()
        records[key + ":not_shared"] = Counter()
    strata = defaultdict(lambda: defaultdict(Counter))
    bins = defaultdict(Counter)
    coverage_bits = bits["all_coverage"]
    neighbor_bits = {}
    for key in METRICS:
        postings = defaultdict(int)
        for i, identity in enumerate(ids):
            for symbol in features[identity][key]:
                postings[symbol] |= 1 << i
        neighbors = []
        for i, identity in enumerate(ids):
            mask = 0
            for symbol in features[identity][key]:
                mask |= postings[symbol]
            neighbors.append(mask & ~(1 << i))
        neighbor_bits[key] = neighbors
    gold_mask = sum(1 << i for i in gold_indices)
    all_mask = (1 << n) - 1
    file_masks, owner_masks = defaultdict(int), defaultdict(int)
    for i, identity in enumerate(ids):
        owner = location(identity)
        file_masks[owner[0]] |= 1 << i
        owner_masks[owner] |= 1 << i
    regions = {"all": [all_mask & ~(1 << i) for i in range(n)],
               "same_source_owner": [owner_masks[location(t)] & ~(1 << i) for i, t in enumerate(ids)],
               "same_file_different_owner": [file_masks[location(t)[0]] & ~owner_masks[location(t)] for t in ids],
               "different_file": [all_mask & ~file_masks[location(t)[0]] for t in ids]}
    def cells(adjacency, region):
        total_degree = sum((mask & part).bit_count() for mask, part in zip(adjacency, region))
        both = sum((adjacency[i] & region[i] & gold_mask).bit_count() for i in gold_indices) // 2
        one = sum((adjacency[i] & region[i] & ~gold_mask).bit_count() for i in gold_indices)
        return Counter(both_updated=both, one_updated=one, neither_updated=total_degree // 2 - both - one)
    for loc, region in regions.items():
        all_cells = cells(regions["all"], region)
        if loc != "all" and not sum(all_cells.values()):
            continue
        target = records if loc == "all" else strata[loc]
        target["all_pairs"] = all_cells
        for key, neighbors in neighbor_bits.items():
            shared_cells = cells(neighbors, region)
            target[key + ":shared"] = shared_cells
            target[key + ":not_shared"] = Counter({k: all_cells[k] - shared_cells[k] for k in all_cells})
    bins["0"] = records["all_coverage:not_shared"].copy()
    for i, ai in enumerate(coverage_bits):
        pending = neighbor_bits["all_coverage"][i] & ~((1 << (i + 1)) - 1)
        while pending:
            bit = pending & -pending
            j = bit.bit_length() - 1
            pending ^= bit
            group = ("both_updated" if i in gold_indices and j in gold_indices else
                     "one_updated" if i in gold_indices or j in gold_indices else "neither_updated")
            shared = (ai & coverage_bits[j]).bit_count()
            union = (ai | coverage_bits[j]).bit_count()
            bins[jaccard_bin(shared, union)][group] += 1
    pair_details = []
    for a, b in combinations(sorted(gold), 2):
        shared = sorted(methods[a]["coverage"] & methods[b]["coverage"])
        union = methods[a]["coverage"] | methods[b]["coverage"]
        detail = {"test_a": a, "test_b": b, "stratum": stratum(a, b),
                             "status_a": methods[a]["coverage_status"], "status_b": methods[b]["coverage_status"],
                             "coverage_a": len(methods[a]["coverage"]), "coverage_b": len(methods[b]["coverage"]),
                             "shared_count": len(shared), "union_count": len(union),
                             "jaccard": rate(len(shared), len(union)),
                             "overlap_coefficient": rate(len(shared), min(len(methods[a]["coverage"]), len(methods[b]["coverage"]))),
                             "feature_shared_counts": {k: len(features[a][k] & features[b][k]) for k in METRICS}}
        if pair_sink is not None:
            pair_sink(detail)
        if len(pair_details) < detail_limit:
            detail["shared_functions"] = [{"id": s, "depth_a": methods[a]["depths"].get(s),
                                                   "depth_b": methods[b]["depths"].get(s),
                                                   "covering_methods": frequency[s],
                                                   "prevalence": frequency[s] / n} for s in shared]
            pair_details.append(detail)
    # Exact aggregate rates are the main output. Permutation is only a
    # descriptive per-PR sensitivity analysis; pairs are not independent trials.
    permutation = {}
    if len(gold) >= 2 and permutations:
        rng = random.Random(seed)
        owner_groups = defaultdict(list)
        counts = Counter(location(t) for t in gold)
        for i, identity in enumerate(ids):
            owner_groups[location(identity)].append(i)
        observed = {k: records[k + ":shared"]["both_updated"] for k in METRICS}
        # Test-neighbor bitsets make each permutation O(k * metrics), rather
        # than enumerating O(k^2) selected pairs for PRs updating many tests.
        for mode in ("uniform", "source_owner_matched"):
            totals = Counter()
            upper_tail = Counter()
            for _ in range(permutations):
                chosen = (rng.sample(range(n), len(gold)) if mode == "uniform" else
                          [i for owner, count in sorted(counts.items())
                           for i in rng.sample(owner_groups[owner], count)])
                chosen_mask = sum(1 << i for i in chosen)
                for key, values in neighbor_bits.items():
                    score = sum((values[i] & chosen_mask).bit_count() for i in chosen) // 2
                    totals[key] += score
                    upper_tail[key] += score >= observed[key]
            permutation[mode] = {k: {"observed_shared_updated_pairs": observed[k],
                                     "null_mean_shared_pairs": totals[k] / permutations,
                                     "upper_tail_fraction_plus_one": (upper_tail[k] + 1) / (permutations + 1)}
                                 for k in METRICS}
    function_rows = [{"function": s, "covering_methods": count,
                      "updated_covering_methods": sum(s in methods[t]["coverage"] for t in gold),
                      "prevalence": count / n, "rare_5pct": s in rare}
                     for s, count in sorted(frequency.items())]
    return {"eligible_methods": n, "updated_methods": len(gold), "updated_ids": sorted(gold),
            "production_functions": len(frequency), "rare_function_count": len(rare),
            "random_partner_update_rate": rate(len(gold) - 1, n - 1) if gold else None,
            "tables": {k: summarize_cells(c) for k, c in records.items()},
            "location_strata": {loc: {k: summarize_cells(c) for k, c in table.items()}
                                for loc, table in strata.items()},
            "jaccard_bins": {key: summarize_cells(c) for key, c in bins.items()},
            "updated_pair_count": len(gold) * (len(gold) - 1) // 2,
            "detailed_pair_limit": detail_limit, "updated_pairs": pair_details, "function_statistics": function_rows,
            "permutation": {"draws": permutations, "seed": seed, "results": permutation}}


def analyze(trace_roots, retrieval_run, output, permutations=10000):
    if output.exists():
        raise ValueError("Use a fresh output directory; existing evidence is not overwritten")
    output.mkdir(parents=True)
    rows = read_json(retrieval_run / "per-pr.json")
    manifests, traces, checks = {}, {}, {}
    # Verify frozen evidence first, then access host-only labels.
    for root in trace_roots:
        index, methods, verification = load_trace(root)
        base = index["base_sha"]
        if base in traces:
            raise ValueError("Ambiguous duplicate base: select one environment/bundle explicitly")
        traces[base] = methods
        checks[base] = verification
        manifests[base] = {"path": str(root / "manifest.json"),
                           "sha256": file_hash(root / "manifest.json")}
    sources = {str(retrieval_run / "per-pr.json"): file_hash(retrieval_run / "per-pr.json")}
    ledger, analyses, results = [], [], []
    for row in rows:
        base, pr_id = row["base_sha"], row["pr_id"]
        label_path = retrieval_run / "evaluation" / f"pr-{pr_id}-labels.json"
        label = read_json(label_path)
        sources[str(label_path)] = file_hash(label_path)
        checksum = label["labels_sha256"]
        if checksum != digest({k: v for k, v in label.items() if k != "labels_sha256"}):
            raise ValueError("Label content seal mismatch")
        if checksum != row["labels_sha256"] or base != label["base_sha"]:
            raise ValueError("Label/base manifest mismatch")
        if not label["complete"]:
            raise ValueError("Incomplete labels cannot be treated as observed nonupdates")
        gold = set(label["testcases"])
        entry = {"pr_id": pr_id, "base_sha": base, "updated_methods": len(gold),
                 "status": "TRACE_AVAILABLE" if base in traces else "MISSING_BASE_TRACE"}
        ledger.append(entry)
        if base not in traces:
            continue
        corpus_path = retrieval_run / "corpora" / f"{base}.json"
        corpus = read_json(corpus_path)
        sources[str(corpus_path)] = file_hash(corpus_path)
        if corpus["base_sha"] != base or corpus["index_sha256"] != label["index_sha256"]:
            raise ValueError("Label candidate index mismatch")
        manifest = read_json(Path(manifests[base]["path"]))
        for item in corpus["entries"]:
            if manifest["source_files"].get(item["path"]) != item["file_sha256"]:
                raise ValueError("Candidate source differs from trace base: " + item["path"])
        candidate_ids = {t["id"] for t in corpus["entries"]}
        if not gold <= candidate_ids:
            raise ValueError("Label identity absent from base candidates")
        methods = traces[base]
        entry["candidate_methods"] = len(candidate_ids)
        entry["candidate_trace_status"] = dict(Counter(methods[t]["coverage_status"] if t in methods else "not_discovered" for t in candidate_ids))
        entry["updated_trace_status"] = dict(Counter(methods[t]["coverage_status"] if t in methods else "not_discovered" for t in gold))
        entry["updated_method_evidence"] = [{"id": t, "coverage_status": methods[t]["coverage_status"] if t in methods else "not_discovered",
                                             "expected_instances": methods[t]["expected_instances"] if t in methods else None,
                                             "valid_instances": methods[t]["valid_instances"] if t in methods else 0} for t in sorted(gold)]
        for cohort, allowed in (("complete_only", {"complete"}),
                                ("available_including_partial", {"complete", "partial"})):
            selected = {t: m for t, m in methods.items() if t in candidate_ids and m["coverage_status"] in allowed}
            print(f"Analyzing PR {pr_id}, {cohort}: {len(selected)} methods", flush=True)
            csv_relative = f"pr-{pr_id}-{cohort}-updated-pairs.csv"
            with (output / csv_relative).open("w", newline="", encoding="utf-8") as handle:
                fields = ["test_a", "test_b", "stratum", "status_a", "status_b", "coverage_a", "coverage_b",
                          "shared_count", "union_count", "jaccard", "overlap_coefficient", *METRICS]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                def save_pair(pair):
                    writer.writerow({**{k: v for k, v in pair.items() if k != "feature_shared_counts"},
                                     **pair["feature_shared_counts"]})
                result = pair_analysis(selected, gold, permutations=permutations, pair_sink=save_pair)
            result.update(pr_id=pr_id, base_sha=base, cohort=cohort,
                          all_updated_pair_counts_csv=csv_relative,
                          labeled_updated_total=len(gold), excluded_updated_ids=sorted(gold - set(selected)),
                          candidate_methods=len(candidate_ids), unknown_or_unavailable_candidates=len(candidate_ids - set(selected)))
            relative = f"pr-{pr_id}-{cohort}.json"
            write_json(output / relative, result)
            analyses.append({"pr_id": pr_id, "base_sha": base, "cohort": cohort, "path": relative})
            results.append(result)
    summary = {"version": VERSION, "scope": "HOST_ONLY_RETROSPECTIVE_ANALYSIS",
               "selected_prs": len(rows), "selected_bases": len({r['base_sha'] for r in rows}),
               "trace_bases": len(traces), "analyzed_prs": sum(r['status'] == 'TRACE_AVAILABLE' for r in ledger),
               "missing_bases": sorted({r['base_sha'] for r in ledger if r['status'] == 'MISSING_BASE_TRACE'}),
               "updated_methods_across_selected_prs": sum(r['updated_methods'] for r in ledger),
               "analyses": analyses, "aggregate": aggregate_results(results), "input_trace_manifests": manifests,
               "input_source_files": sources, "trace_verification": checks,
               "protocol": {"primary": "complete_only", "exploratory": "available_including_partial",
                            "identity": "base + source path::qualified_name; inherited and parameter instances collapsed",
                            "coverage": "production functions from validated passing test bodies only",
                            "depth": "minimum root BFS distance over individual execution function graphs; never union-instance paths",
                            "depth_is_not": "temporal stack depth, causal distance or an assertion-dependence proof",
                            "unknown": "excluded from pair denominators with explicit ledger, never replaced with empty coverage",
                            "unmodified": "not observed updated in this PR; not confirmed unnecessary-to-update",
                            "rarity": "function covered by <=5% of eligible candidate source methods, computed without labels",
                            "pair_unit": "unordered pair within one PR/base, never cross-base edges",
                            "dependence": "pairs and shared bases are dependent; no pairwise binomial significance claim",
                            "permutation_draws": permutations,
                            "models_or_new_test_executions": 0}}
    write_json(output / "base-pr-ledger.json", ledger)
    with (output / "base-pr-ledger.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pr_id", "base_sha", "updated_methods", "status"], extrasaction="ignore")
        writer.writeheader(); writer.writerows(ledger)
    write_json(output / "summary.json", summary)
    render_report(output, summary, ledger)
    sources_final = {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}
    write_json(output / "analysis-manifest.json", {"version": VERSION, "files": sources_final,
               "implementation_sha256": file_hash(Path(__file__)), "input_trace_manifests": manifests})
    return summary


def percent(value):
    if value is None:
        return "不可估计"
    return f"{value:.5%}" if 0 < value < 0.001 else f"{value:.2%}"


def aggregate_results(results):
    """Preserve equal-PR macro and pooled descriptive counts separately."""
    aggregate = {}
    for cohort in sorted({r["cohort"] for r in results}):
        selected = [r for r in results if r["cohort"] == cohort]
        table = {}
        for metric in METRICS:
            summed = Counter()
            macro_shared, macro_seed = [], []
            for result in selected:
                row = result["tables"][metric + ":shared"]
                summed.update({k: row[k] for k in ("both_updated", "one_updated", "neither_updated")})
                shared_ratio = rate(row["both_updated"], result["tables"]["all_pairs"]["both_updated"])
                if shared_ratio is not None:
                    macro_shared.append(shared_ratio)
                if row["p_partner_updated_given_updated_seed"] is not None:
                    macro_seed.append(row["p_partner_updated_given_updated_seed"])
            table[metric] = {"pooled_shared_pair_cells": summarize_cells(summed),
                             "macro_fraction_updated_pairs_sharing": rate(sum(macro_shared), len(macro_shared)),
                             "macro_fraction_denominator_prs": len(macro_shared),
                             "macro_partner_update_rate_given_shared_updated_seed": rate(sum(macro_seed), len(macro_seed)),
                             "macro_partner_denominator_prs": len(macro_seed)}
        aggregate[cohort] = {"prs": len(selected), "bases": len({r["base_sha"] for r in selected}),
                             "metrics": table,
                             "uncertainty": "Descriptive only; no independent-pair significance or multi-base inference"}
    return aggregate


def render_report(output, summary, ledger):
    lines = ["# 测试覆盖、调用层级与同 PR 共同修改：初步分析", "",
             f"既有样本包含 {summary['selected_prs']} 个 PR、{summary['selected_bases']} 个 base；本次有冻结动态证据的 base 为 {summary['trace_bases']} 个，对应 {summary['analyzed_prs']} 个 PR。",
             "这是宿主机回顾性标签分析，不是更新定位效果评价；结果不进入 SDD 输入包，不修改冻结轨迹，也不调用模型或重新执行测试。", "",
             "主分析仅使用覆盖完整的源码测试方法；含部分覆盖的方法另列为探索性结果。未知覆盖不按空集合处理。未观察到修改不等于不需要修改。", "",
             "## 两个问题的分母", "",
             "1. 共同更新的测试是否共享覆盖：共同更新且有覆盖证据的测试对中，共享生产函数的比例。",
             "2. 共享覆盖是否往往共同更新：分别统计所有无序测试对中的共同更新率，以及已知一个测试被更新时，共享覆盖的另一测试也被更新的条件比例。二者不能互相替代。",
             "3. 对照同一 PR/base 的未共享测试对，并分同源码 owner（通常为同类）、同文件不同 owner、跨文件；另使用保持每个源码 owner 更新数量的随机对照。", "",
             "## 调用层级口径", "",
             "每条调用边是观察到的直接 Python 父帧调用。层级取每个独立执行实例内从测试根到生产函数的 BFS 最短距离，再跨该源码方法的有效实例取最小值。禁止把不同实例的边拼成一条路径。函数图本身会折叠重复调用，因此层级不是最大实际栈深度，也不是因果距离。",
             "无法沿内部边连接到根的覆盖单独标为 root_unreachable，不解释为无覆盖或无限深。完整覆盖、根可达、深度≤1/2/3/5、深度≥4和低频共享函数分别统计。低频阈值预先固定为覆盖该函数的方法不超过当前候选集的5%。", ""]
    for ref in summary["analyses"]:
        result = read_json(output / ref["path"])
        lines += [f"## PR #{ref['pr_id']} / {ref['cohort']}", "",
                  f"base `{ref['base_sha']}`。纳入 {result['eligible_methods']} 个测试方法；该 PR 的 {result['labeled_updated_total']} 个更新测试中纳入 {result['updated_methods']} 个。候选中其余 {result['unknown_or_unavailable_candidates']} 个不在本 cohort 的可分析分母。",
                  f"全部测试对 {result['tables']['all_pairs']['pairs']:,}；共同更新对 {result['tables']['all_pairs']['both_updated']}。随机选一个其他候选的更新比例为 {percent(result['random_partner_update_rate'])}。", "",
                  "| 共享条件 | 共同更新对中的共享比例 | 所有共享对中的共同更新率 | 已更新种子的共享伙伴更新率 | 无共享伙伴更新率 |",
                  "|---|---:|---:|---:|---:|"]
        denominator = result["tables"]["all_pairs"]["both_updated"]
        for metric in METRICS:
            shared, absent = (result["tables"][metric + ":" + suffix] for suffix in ("shared", "not_shared"))
            lines.append(f"| {metric} | {shared['both_updated']}/{denominator} ({percent(rate(shared['both_updated'], denominator))}) | {percent(shared['p_both_observed_updated'])} | {percent(shared['p_partner_updated_given_updated_seed'])} | {percent(absent['p_partner_updated_given_updated_seed'])} |")
        if not denominator:
            lines += ["", "本 cohort 没有可分析的共同更新测试对，不能估计第一个问题，也不能据此否定关系。"]
        if result["updated_pairs"]:
            lines += ["", f"共有 {result.get('updated_pair_count', len(result['updated_pairs']))} 个共同更新测试对；全部对的计数保存在 `{result.get('all_updated_pair_counts_csv', '')}`。下表及逐函数细节最多展示按身份排序的前 {result.get('detailed_pair_limit', 100)} 对，避免大规模修改 PR 生成不可阅读的报告；不影响所有对的统计。"]
            lines += ["", "### 共同更新测试对", "", "| 测试 A | 测试 B | 各自覆盖数 | 共享数 | Jaccard | 位置关系 |", "|---|---|---:|---:|---:|---|"]
            for pair in result["updated_pairs"]:
                lines.append(f"| `{pair['test_a']}` | `{pair['test_b']}` | {pair['coverage_a']} / {pair['coverage_b']} | {pair['shared_count']} | {percent(pair['jaccard'])} | {pair['stratum']} |")
            lines += ["", "每个共享函数在两侧的层级（null 表示内部根不可达）、函数覆盖普遍度与各层级共享数量已完整保存在本 cohort 的 JSON 中。"]
            lines += ["", "### 共享函数的层级分布", "", "| 测试对 | 双方≤1层 | 双方≤2层 | 双方≤3层 | 双方≥4层 | 双方内部根不可达 |", "|---|---:|---:|---:|---:|---:|"]
            for i, pair in enumerate(result["updated_pairs"], 1):
                counts = pair["feature_shared_counts"]
                lines.append(f"| 上表第 {i} 对 | {counts['depth_le_1']} | {counts['depth_le_2']} | {counts['depth_le_3']} | {counts['depth_ge_4']} | {counts['root_unreachable']} |")
            for i, pair in enumerate(result["updated_pairs"], 1):
                if pair["shared_count"] <= 20:
                    lines += ["", f"第 {i} 对的全部共享函数：", "", "| 函数 | A侧层级 | B侧层级 | 当前候选覆盖普遍度 |", "|---|---:|---:|---:|"]
                    for symbol in pair["shared_functions"]:
                        da = symbol['depth_a'] if symbol['depth_a'] is not None else '根不可达'
                        db = symbol['depth_b'] if symbol['depth_b'] is not None else '根不可达'
                        lines.append(f"| `{symbol['id']}` | {da} | {db} | {percent(symbol['prevalence'])} |")
        lines += ["", "### 位置对照（完整覆盖共享）", "", "| 位置 | 共同更新对 | 共享对 | 已更新种子的共享伙伴更新率 | 无共享伙伴更新率 |", "|---|---:|---:|---:|---:|"]
        for loc, tables in result["location_strata"].items():
            shared, absent = tables.get("all_coverage:shared", summarize_cells({})), tables.get("all_coverage:not_shared", summarize_cells({}))
            lines.append(f"| {loc} | {tables['all_pairs']['both_updated']} | {shared['pairs']} | {percent(shared['p_partner_updated_given_updated_seed'])} | {percent(absent['p_partner_updated_given_updated_seed'])} |")
        if result["permutation"]["results"]:
            lines += ["", "### 随机对照", "", "| 共享条件 | 实际共同更新共享对数 | 均匀随机期望 | 保持源码 owner 更新数量的随机期望 |", "|---|---:|---:|---:|"]
            samples = result["permutation"]["results"]
            for metric in METRICS:
                a, b = samples["uniform"][metric], samples["source_owner_matched"][metric]
                lines.append(f"| {metric} | {a['observed_shared_updated_pairs']} | {a['null_mean_shared_pairs']:.3f} | {b['null_mean_shared_pairs']:.3f} |")
            lines += ["", "随机对照仅作该 PR 的描述性敏感性检查；JSON 中保留随机种子、抽样次数及尾部比例。单个 PR、少量更新对和相关测试对不能支撑总体显著性结论。"]
    lines += ["", "## 解释边界与后续复用", "",
              "共享基础设施会使大量未共同修改测试共享覆盖；因此共享集合可以提供关联证据，不能单独作为更新必要性的判据。层级与低频过滤是否更有区分力，应同时比较共享/不共享的条件比例、位置对照和多 PR 结果。",
              "深层共享为零不能推断深层不重要：异步框架和外部边界会让已覆盖函数无法沿内部边从根到达。root_unreachable 指双方均不可达的共享函数；只有一侧不可达时仍保留在每个共享函数的两侧层级记录中。",
              "应核查实际覆盖 PR 的修改动机，区分行为变化、测试修复、恢复跳过与机械修改；少量特定类型 PR 不能代表一般行为变更。summary.json 分别保存等权 PR 宏平均与合并测试对计数，未覆盖 PR 不会被静默填零。",
              "其余 base 见 base-pr-ledger.csv。本程序支持多个 --trace-bundle；后续先从每个 base 独立构建、冻结全量覆盖，再在宿主侧连接修改标签。禁止用这次标签筛选采集测试，禁止把本分析、更新列表或标签送入受控 SDD Agent。",
              "扩大范围后应同时报告逐 PR 结果与等权 PR 宏平均，并按 base/时间聚类估计不确定性；不能让一次大规模批量修改或重复 base 把总体关系夸大。跨 PR 的某对测试共同修改频率还需要严格定义两者同时存在且可观测的机会窗口；当前分析回答每个 PR 内的共同更新关联。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-bundle", action="append", required=True, type=Path)
    parser.add_argument("--retrieval-run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--permutations", type=int, default=10000)
    args = parser.parse_args(argv)
    if args.permutations < 0:
        parser.error("--permutations must be nonnegative")
    result = analyze([p.resolve() for p in args.trace_bundle], args.retrieval_run.resolve(), args.output.resolve(), args.permutations)
    print(json.dumps({k: result[k] for k in ("selected_prs", "selected_bases", "trace_bases", "analyzed_prs")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
