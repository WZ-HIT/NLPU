#!/usr/bin/env python3
"""Build draft case records and Markdown notes for the five pilot PRs.

The generated records are candidates for human review. Every edge and every
no-edge counterfactual starts as ``candidate`` / ``unknown``; the reviewer must
confirm or reject them. No model, Docker, or network call is made.

Usage:
    python3 sdd-bench/scrapy-sdd/batch/case-analysis/tools/build_pilot_cases.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from callgraph import ambiguity_note, build_graph, shortest_path

CASE_DIR = Path(__file__).resolve().parents[1]
BENCH_DIR = CASE_DIR.parents[1]
REPO_ROOT = BENCH_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
INVENTORY = BENCH_DIR / "batch/inventories/scrapy-pr-inventory.json"
GOLD_DIR = BENCH_DIR / "batch/gold"
WORKSPACES = BENCH_DIR / "batch/workspaces"
PRECLASS = CASE_DIR / "preclassification.json"
CASES_DIR = CASE_DIR / "cases"
EDGES_JSONL = CASE_DIR / "edges.jsonl"

PILOTS = {
    7605: ("direct", "Single modified test with a direct static_call to one changed production function."),
    7647: ("indirect", "Single modified test connected by static_call_path to one changed production method."),
    7520: ("no_edge", "Single modified test and three changed production symbols with no direct/indirect candidate."),
    6546: ("mixed", "Four tests: three direct edges coexist with fifteen production symbols that have no candidate test connection."),
    7684: ("mixed", "Nine tests: indirect edges, weak-only evidence, and uncovered production symbols coexist."),
}

EVIDENCE_MAP = {
    "static_call": "static_call",
    "static_call_path": "static_call_path",
    "coverage": "coverage",
    "module_import": "import",
}
WEAK = {"module_import", "name_overlap", "diff_proximity"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def base_repo(pr_id: int) -> Path:
    return WORKSPACES / f"scrapy__scrapy__pr{pr_id}/cc-sdd/repository"


def gold_ref(pr_id: int, section: str, index: int) -> str:
    return f"batch/gold/scrapy__scrapy__pr{pr_id}/gold-store.json#{section}[{index}]"


def patch_for(gold: dict[str, Any], section: str, path: str) -> str:
    for index, item in enumerate(gold.get(section) or []):
        if item.get("path") == path:
            return item.get("patch", "")
    return ""


def truncate(text: str, limit: int = 80) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit]) + f"\n... ({len(lines) - limit} lines omitted; see gold store)"


def build_case(
    record: dict[str, Any],
    pre: dict[str, Any],
    gold: dict[str, Any],
    graph: dict[str, set[str]],
    locations: dict[str, set[str]],
) -> dict[str, Any]:
    pr_id = record["pr_id"]
    case_id = f"pr-{pr_id}"
    stratum, rationale = PILOTS[pr_id]

    production_changes: list[dict[str, Any]] = []
    patch_index = {
        item["path"]: index
        for index, item in enumerate(gold.get("production_patches") or [])
    }
    for item in pre["production_changes"]:
        production_changes.append(
            {
                "path": item["path"],
                "symbol": item["symbol"],
                "kind": item["kind"],
                "change_kind": "unknown",
                "hunks": item.get("hunks") or [item["hunk"]],
                "evidence_ref": gold_ref(
                    pr_id, "production_patches", patch_index.get(item["path"], 0)
                ),
            }
        )

    modified_tests = [
        {"path": change["path"], "qualified_name": change["qualified_name"]}
        for change in record.get("test_changes") or []
        if change.get("change_type") == "modified"
    ]

    edges: list[dict[str, Any]] = []
    weak_by_production: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in pre["edge_candidates"]:
        evidence = [
            EVIDENCE_MAP[item]
            for item in candidate["evidence"]
            if item in EVIDENCE_MAP
        ]
        if candidate["relation_candidate"] == "weak" or not evidence:
            key = (
                candidate["production"]["path"],
                candidate["production"]["symbol"],
            )
            weak_by_production[key].append(candidate)
            continue
        relation = candidate["relation_candidate"]
        test_qname = candidate["test"]["qualified_name"]
        production_symbol = candidate["production"]["symbol"]
        test_def = {
            "calls": candidate.get("test", {}).get("calls", []),
        }
        # Raw pair evidence does not carry the test's calls; recover them from
        # the base test definition when possible.
        test_path = base_repo(pr_id) / candidate["test"]["path"]
        if test_path.exists():
            try:
                from experiment.ast_extract import extract_definitions  # noqa: PLC0415

                definitions = extract_definitions(
                    test_path.read_text(encoding="utf-8"),
                    candidate["test"]["path"],
                )
                for definition in definitions:
                    if definition.qualified_name == test_qname:
                        test_def["calls"] = list(definition.calls)
                        break
            except (SyntaxError, KeyError):
                pass
        if relation == "indirect":
            path = candidate.get("ast_path") or shortest_path(
                graph, test_def["calls"], production_symbol.split(".")[-1]
            )
        else:
            path = [test_qname, production_symbol]
        if relation == "direct":
            path = [test_qname, production_symbol]
            hops = 1
            if candidate.get("source") == "base_ast_fallback":
                rationale = (
                    "Base AST: the test calls this definition directly; the raw "
                    "pair evidence did not report the edge."
                )
            else:
                rationale = "Direct raw-pair evidence: " + ", ".join(evidence)
        elif path and len(path) >= 2:
            hops = len(path)
            note = ambiguity_note(path, locations)
            path = [test_qname, *path]
            if candidate.get("source") == "base_ast_weak_upgrade":
                rationale = (
                    "Raw pair reported only weak evidence; the base AST call graph "
                    "supplies this path and hop count for reviewer confirmation."
                    + note
                )
            else:
                rationale = (
                    "Raw pair reports static_call_path; draft BFS path and hop count "
                    "shown for reviewer confirmation." + note
                )
        elif path:
            # Raw evidence says static_call_path, but the base call set already
            # contains the target leaf. Leave the exact depth unresolved rather
            # than silently reporting a direct distance.
            hops = None
            path = []
            rationale = (
                "Raw pair reports static_call_path, but the base call set already "
                "contains the target leaf; exact hops need reviewer resolution."
            )
        else:
            hops = None
            path = []
            rationale = (
                "Raw pair reports static_call_path; exact path not resolved by "
                "the draft BFS and needs reviewer resolution."
            )
        edges.append(
            {
                "edge_id": f"{case_id}:{test_qname}->{production_symbol}",
                "test": {
                    "path": candidate["test"]["path"],
                    "qualified_name": test_qname,
                },
                "production": {
                    "path": candidate["production"]["path"],
                    "symbol": production_symbol,
                },
                "relation": relation,
                "hops": hops,
                "path": path or [],
                "evidence": evidence,
                "confidence": (
                    "low"
                    if candidate.get("source") == "base_ast_weak_upgrade"
                    else "high" if relation == "direct" else "medium"
                ),
                "status": "candidate",
                "rationale": rationale,
            }
        )

    no_edge_changes: list[dict[str, Any]] = []
    for item in pre["no_edge_candidates"]:
        key = (item["path"], item["symbol"])
        weak = weak_by_production.get(key, [])
        weak_note = ""
        if weak:
            tests = sorted({candidate["test"]["qualified_name"] for candidate in weak})
            weak_note = " Weak-only candidates (not counted as edges): " + ", ".join(tests) + "."
        no_edge_changes.append(
            {
                "production": {"path": item["path"], "symbol": item["symbol"]},
                "change_kind": "unknown",
                "counterfactual": "unknown",
                "coverage_gap": False,
                "affected_existing_tests": [],
                "confidence": "low",
                "status": "candidate",
                "rationale": (
                    "No direct/indirect candidate from any modified existing test in the pre-classification."
                    + weak_note
                ),
            }
        )

    return {
        "schema_version": 1,
        "case_id": case_id,
        "pr_id": pr_id,
        "repo": "scrapy/scrapy",
        "base_sha": record["recorded_base_sha"],
        "head_sha": (gold.get("future_revisions") or {}).get("head"),
        "merge_sha": (gold.get("future_revisions") or {}).get("merge"),
        "classification": "MIXED_CODE_AND_TEST_PR",
        "selection": {"stratum": stratum, "rationale": rationale},
        "production_changes": production_changes,
        "modified_tests": modified_tests,
        "edges": edges,
        "no_edge_changes": no_edge_changes,
        "test_level": {
            "positives": modified_tests,
            "missed_updates": [],
            "coverage_gaps": [],
            "unknown": [],
        },
        "review": {
            "status": "draft",
            "first_pass_at": None,
            "second_pass_at": None,
            "changed_verdicts": [],
        },
        "notes": (
            "Pre-classification dominant="
            f"{pre['dominant_relation_candidate']} "
            f"counts={json.dumps(pre['counts'], sort_keys=True)}. "
            "Auto-generated candidate record. Reviewer must confirm/reject every "
            "edge, assign change_kind and counterfactual, and check for resolver "
            "gaps."
        ),
    }


def render_markdown(case: dict[str, Any], gold: dict[str, Any]) -> str:
    pr_id = case["pr_id"]
    lines: list[str] = []
    lines.append(f"# PR #{pr_id} — 连接关系案例（draft）")
    lines.append("")
    lines.append(f"- 案例 ID：`{case['case_id']}`")
    lines.append(f"- base：`{case['base_sha']}`")
    lines.append(f"- head：`{case['head_sha']}`")
    lines.append(f"- 选样层：`{case['selection']['stratum']}`")
    lines.append(f"- 状态：`{case['review']['status']}`，所有边与反事实均为候选")
    lines.append("")
    lines.append("## 生产改动")
    lines.append("")
    lines.append("| 文件 | 符号 | 类型 | change_kind | hunk |")
    lines.append("| --- | --- | --- | --- | --- |")
    for item in case["production_changes"]:
        lines.append(
            f"| `{item['path']}` | `{item['symbol']}` | {item['kind']} | "
            f"{item['change_kind']} | {item['hunks']} |"
        )
    lines.append("")
    lines.append("## 被修改的既有测试")
    lines.append("")
    lines.append("| 文件 | 测试 |")
    lines.append("| --- | --- |")
    for item in case["modified_tests"]:
        lines.append(f"| `{item['path']}` | `{item['qualified_name']}` |")
    lines.append("")
    lines.append("## 候选边")
    lines.append("")
    if case["edges"]:
        lines.append("| 测试 | 生产符号 | 类型 | 跳数 | 路径 | 证据 | 置信度 | 状态 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for edge in case["edges"]:
            path = " → ".join(edge["path"]) if edge["path"] else "（未解析）"
            lines.append(
                f"| `{edge['test']['qualified_name']}` | `{edge['production']['symbol']}` | "
                f"{edge['relation']} | {edge['hops']} | {path} | "
                f"{', '.join(edge['evidence'])} | "
                f"{edge['confidence']} | {edge['status']} |"
            )
        lines.append("")
        lines.append("边理由：")
        lines.append("")
        for edge in case["edges"]:
            lines.append(f"- `{edge['edge_id']}`：{edge['rationale']}")
    else:
        lines.append("（无直接/间接候选边）")
    lines.append("")
    lines.append("## 无测试连接的生产符号")
    lines.append("")
    if case["no_edge_changes"]:
        lines.append("| 文件 | 符号 | 反事实 | coverage_gap | 置信度 | 备注 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for item in case["no_edge_changes"]:
            lines.append(
                f"| `{item['production']['path']}` | `{item['production']['symbol']}` | "
                f"{item['counterfactual']} | {item['coverage_gap']} | "
                f"{item['confidence']} | {item['rationale']} |"
            )
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("## 生产 diff 片段")
    lines.append("")
    for item in gold.get("production_patches") or []:
        if not item["path"].startswith("scrapy/") or not item["path"].endswith(".py"):
            continue
        lines.append(f"### `{item['path']}`")
        lines.append("")
        lines.append("```diff")
        lines.append(truncate(item.get("patch", "")))
        lines.append("```")
        lines.append("")
    lines.append("## 测试 diff 片段")
    lines.append("")
    for item in gold.get("test_patches") or []:
        lines.append(f"### `{item['path']}`")
        lines.append("")
        lines.append("```diff")
        lines.append(truncate(item.get("patch", ""), limit=60))
        lines.append("```")
        lines.append("")
    lines.append("## 复核清单")
    lines.append("")
    lines.append("- [ ] 确认/推翻每条候选边，并补充语义理由。")
    lines.append("- [ ] 对每个无连接生产符号判定 `no_update_needed` / `missed` / `unknown`，并标注 `change_kind`。")
    lines.append("- [ ] 检查是否有预分漏掉的间接关系（尤其 fixture、配置、事件、数据传播）。")
    lines.append("- [ ] 检查 `coverage_gap`：是否应新增测试而非修改既有测试。")
    lines.append("- [ ] 检查 gold patch 之外的模块级改动是否影响连接判断。")
    lines.append("")
    lines.append("> 本文件只内联必要的 diff 片段；完整补丁见 `batch/gold/<task>/gold-store.json`。不得作为模型输入。")
    return "\n".join(lines) + "\n"


def main() -> int:
    inventory = {
        record["pr_id"]: record
        for record in load_json(INVENTORY)["pull_requests"]
    }
    preclass = {
        item["pr_id"]: item
        for item in load_json(PRECLASS)["candidates"]
    }
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    edge_rows: list[dict[str, Any]] = []
    for pr_id, (stratum, _) in PILOTS.items():
        record = inventory[pr_id]
        pre = preclass[pr_id]
        gold = load_json(GOLD_DIR / f"scrapy__scrapy__pr{pr_id}/gold-store.json")
        graph, locations = build_graph(base_repo(pr_id))
        case = build_case(record, pre, gold, graph, locations)
        case_path = CASES_DIR / f"pr{pr_id}.json"
        case_path.write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        md_path = CASES_DIR / f"pr{pr_id}.md"
        md_path.write_text(render_markdown(case, gold), encoding="utf-8")
        for edge in case["edges"]:
            edge_rows.append(
                {
                    "case_id": case["case_id"],
                    "pr_id": pr_id,
                    **edge,
                }
            )
        print(
            f"wrote {case_path.name}, {md_path.name}: "
            f"{len(case['edges'])} edges, {len(case['no_edge_changes'])} no-edge"
        )

    EDGES_JSONL.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in edge_rows) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {EDGES_JSONL.name} ({len(edge_rows)} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
