#!/usr/bin/env python3
"""Pre-classify mixed Scrapy PRs for the connection case analysis.

This is a candidate generator, not a ground-truth labeler. It answers two
questions per PR:

1. Which Python production definitions were touched by the PR?
2. Which modified existing tests have static evidence connecting them to those
   definitions, and which production definitions have no such connection?

The output is deliberately conservative: every edge is a candidate that must be
confirmed or rejected by the human reviewer. No service, Docker, or model call
is made.

Usage:
    python3 sdd-bench/scrapy-sdd/batch/case-analysis/tools/preclassify.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from callgraph import build_graph, shortest_path

CASE_DIR = Path(__file__).resolve().parents[1]
BENCH_DIR = CASE_DIR.parents[1]
REPO_ROOT = BENCH_DIR.parents[1]
INVENTORY = BENCH_DIR / "batch/inventories/scrapy-pr-inventory.json"
GOLD_DIR = BENCH_DIR / "batch/gold"
WORKSPACES = BENCH_DIR / "batch/workspaces"
RAW_PRS = REPO_ROOT / "output/raw_prs/scrapy__scrapy.jsonl"
OUTPUT = CASE_DIR / "preclassification.json"

MAX_MODIFIED_TESTS = 20
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
HEADER_DEF_RE = re.compile(r"\b(?:def|class)\s+(\w+)")

DIRECT_EVIDENCE = {"coverage", "static_call"}
INDIRECT_EVIDENCE = {"static_call_path"}
WEAK_EVIDENCE = {"module_import", "name_overlap", "diff_proximity"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_raw_pairs() -> dict[int, list[dict[str, Any]]]:
    pairs: dict[int, list[dict[str, Any]]] = {}
    if not RAW_PRS.exists():
        return pairs
    for line in RAW_PRS.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        pairs[record["pr_id"]] = record.get("method_test_pairs") or []
    return pairs


def load_gold() -> dict[int, dict[str, Any]]:
    stores: dict[int, dict[str, Any]] = {}
    for path in sorted(GOLD_DIR.glob("*/gold-store.json")):
        store = load_json(path)
        pr_id = int(store["task_id"].split("pr")[-1])
        stores[pr_id] = store
    return stores


def base_repo(pr_id: int) -> Path:
    return WORKSPACES / f"scrapy__scrapy__pr{pr_id}/cc-sdd/repository"


def parse_definitions(source: str, path: str) -> list[Any]:
    """Reuse the project's AST extractor when available."""
    sys.path.insert(0, str(REPO_ROOT))
    from experiment.ast_extract import extract_definitions  # noqa: PLC0415

    return extract_definitions(source, path)


def enclosing_definitions(
    definitions: list[Any], start: int, end: int
) -> list[Any]:
    """Return the innermost definitions overlapping a patch line range."""
    hits = [
        definition
        for definition in definitions
        if definition.start_line <= end and definition.end_line >= start
    ]
    hits.sort(key=lambda definition: definition.end_line - definition.start_line)
    if not hits:
        return []
    # Keep the innermost hit but also record an enclosing method for nested code.
    innermost = hits[0]
    return [innermost]


def changed_production_symbols(
    repo: Path, patches: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Map each production patch hunk to base definitions and header names."""
    symbols: list[dict[str, Any]] = []
    notes: list[str] = []
    cache: dict[str, list[Any]] = {}
    for patch in patches:
        path = patch["path"]
        if not (path.startswith("scrapy/") and path.endswith(".py")):
            continue
        file_path = repo / path
        if not file_path.exists():
            notes.append(f"missing base file: {path}")
            continue
        if path not in cache:
            try:
                cache[path] = parse_definitions(
                    file_path.read_text(encoding="utf-8"), path
                )
            except SyntaxError as exc:
                notes.append(f"parse error: {path}: {exc}")
                cache[path] = []
        for raw_line in patch.get("patch", "").splitlines():
            match = HUNK_RE.match(raw_line)
            if not match:
                continue
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            old_end = old_start + max(old_count, 1) - 1
            header = match.group(5).strip()
            header_name = HEADER_DEF_RE.search(header)
            hits = enclosing_definitions(cache[path], old_start, old_end)
            if hits:
                for definition in hits:
                    symbols.append(
                        {
                            "path": path,
                            "symbol": definition.qualified_name,
                            "kind": definition.kind,
                            "hunk": [old_start, old_end],
                            "source": "ast",
                        }
                    )
            elif header_name:
                symbols.append(
                    {
                        "path": path,
                        "symbol": header_name.group(1),
                        "kind": "header",
                        "hunk": [old_start, old_end],
                        "source": "hunk_header",
                    }
                )
            else:
                # Module-level change (imports, constants, class bodies with no
                # function hit). Keep it so the no-edge analysis can see it.
                symbols.append(
                    {
                        "path": path,
                        "symbol": "<module>",
                        "kind": "module",
                        "hunk": [old_start, old_end],
                        "source": "module_level",
                    }
                )
    # De-duplicate by (path, symbol) but keep every hunk that touches it: one
    # symbol often spans several hunks, and dropping them hides changes from
    # the reviewer.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in symbols:
        key = (item["path"], item["symbol"])
        existing = unique.get(key)
        if existing is None:
            unique[key] = {**item, "hunks": [item["hunk"]]}
        elif item["hunk"] not in existing["hunks"]:
            existing["hunks"].append(item["hunk"])
    for item in unique.values():
        item["hunks"].sort()
    return list(unique.values()), notes


def pair_edges(
    pairs: list[dict[str, Any]], test_qname: str
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for pair in pairs:
        test_change = pair.get("test_change") or {}
        if test_change.get("qualified_name") != test_qname:
            continue
        if test_change.get("change_type") != "modified":
            continue
        focal = pair.get("focal_method") or {}
        evidence = [
            item.split(":", 1)[0] for item in (pair.get("pair_evidence") or [])
        ]
        if DIRECT_EVIDENCE & set(evidence):
            relation = "direct"
        elif INDIRECT_EVIDENCE & set(evidence):
            relation = "indirect"
        elif WEAK_EVIDENCE & set(evidence):
            relation = "weak"
        else:
            continue
        edges.append(
            {
                "test": {
                    "path": test_change.get("file"),
                    "qualified_name": test_qname,
                },
                "production": {
                    "path": focal.get("file"),
                    "symbol": focal.get("qualified_name"),
                },
                "relation_candidate": relation,
                "evidence": evidence,
                "source": "raw_pair",
            }
        )
    return edges


def resolve_test(repo: Path, path: str, qualified_name: str) -> Any | None:
    file_path = repo / path
    if not file_path.exists():
        return None
    try:
        definitions = parse_definitions(file_path.read_text(encoding="utf-8"), path)
    except SyntaxError:
        return None
    for definition in definitions:
        if definition.qualified_name == qualified_name:
            return definition
    return None


def main() -> int:
    inventory = load_json(INVENTORY)["pull_requests"]
    gold = load_gold()
    raw_pairs = load_raw_pairs()

    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for record in inventory:
        pr_id = record["pr_id"]
        if record["classification"] != "MIXED_CODE_AND_TEST_PR":
            continue
        store = gold.get(pr_id)
        if not store:
            excluded.append({"pr_id": pr_id, "reason": "missing gold store"})
            continue
        production_patches = store.get("production_patches") or []
        package_patches = [
            patch
            for patch in production_patches
            if patch.get("path", "").startswith("scrapy/")
            and patch.get("path", "").endswith(".py")
        ]
        modified_tests = [
            change
            for change in record.get("test_changes") or []
            if change.get("change_type") == "modified"
        ]
        if not package_patches:
            excluded.append({"pr_id": pr_id, "reason": "no package Python change"})
            continue
        if not 1 <= len(modified_tests) <= MAX_MODIFIED_TESTS:
            excluded.append(
                {
                    "pr_id": pr_id,
                    "reason": f"modified test count {len(modified_tests)} outside 1..{MAX_MODIFIED_TESTS}",
                }
            )
            continue
        repo = base_repo(pr_id)
        if not repo.is_dir():
            excluded.append({"pr_id": pr_id, "reason": "missing base worktree"})
            continue

        production, notes = changed_production_symbols(repo, package_patches)
        production_keys = {
            (symbol["path"], symbol["symbol"]) for symbol in production
        }
        production_by_leaf: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for symbol in production:
            production_by_leaf[symbol["symbol"].split(".")[-1]].append(symbol)
        graph: dict[str, set[str]] | None = None

        def call_graph() -> dict[str, set[str]]:
            nonlocal graph
            if graph is None:
                graph, _ = build_graph(repo)
            return graph

        pairs = raw_pairs.get(pr_id) or []
        edges: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        for change in modified_tests:
            path = change["path"]
            qname = change["qualified_name"]
            test_def = resolve_test(repo, path, qname)
            if test_def is None:
                unresolved.append({"path": path, "qualified_name": qname})
                continue
            candidate_edges = pair_edges(pairs, qname)
            strong_keys = {
                (edge["production"]["path"], edge["production"]["symbol"])
                for edge in candidate_edges
                if edge["relation_candidate"] in {"direct", "indirect"}
            }
            # Direct-call fallback on the base AST. It is per (test, production)
            # pair, so it must run even when raw pairs already reported weak
            # evidence for the same test.
            called = {name.split(".")[-1] for name in (test_def.calls or ())}
            for name in sorted(called & production_by_leaf.keys()):
                for symbol in production_by_leaf[name]:
                    key = (symbol["path"], symbol["symbol"])
                    if key in strong_keys:
                        continue
                    strong_keys.add(key)
                    candidate_edges.append(
                        {
                            "test": {"path": path, "qualified_name": qname},
                            "production": {
                                "path": symbol["path"],
                                "symbol": symbol["symbol"],
                            },
                            "relation_candidate": "direct",
                            "evidence": ["static_call"],
                            "source": "base_ast_fallback",
                        }
                    )
            # Upgrade weak raw-pair evidence only when the base call graph shows
            # a real path. Without this, helper-mediated connections (test ->
            # test helper -> changed function) are misreported as no-edge.
            for edge in candidate_edges:
                if edge["relation_candidate"] != "weak":
                    continue
                key = (edge["production"]["path"], edge["production"]["symbol"])
                if key in strong_keys or key not in production_keys:
                    continue
                ast_path = shortest_path(
                    call_graph(),
                    test_def.calls or (),
                    edge["production"]["symbol"].split(".")[-1],
                )
                if not ast_path:
                    continue
                edge["relation_candidate"] = (
                    "direct" if len(ast_path) == 1 else "indirect"
                )
                edge["evidence"] = [
                    "static_call" if len(ast_path) == 1 else "static_call_path",
                    *edge["evidence"],
                ]
                edge["source"] = "base_ast_weak_upgrade"
                edge["ast_path"] = ast_path
                strong_keys.add(key)
            edges.extend(
                edge
                for edge in candidate_edges
                if edge["relation_candidate"] != "weak"
                or (edge["production"]["path"], edge["production"]["symbol"])
                not in strong_keys
            )

        matched_keys = {
            (edge["production"]["path"], edge["production"]["symbol"])
            for edge in edges
            if edge["relation_candidate"] in {"direct", "indirect"}
        }
        no_edge = [
            symbol
            for symbol in production
            if (symbol["path"], symbol["symbol"]) not in matched_keys
        ]
        counts = Counter(edge["relation_candidate"] for edge in edges)
        counts["no_edge"] = len(no_edge)
        classes = {
            key: counts.get(key, 0) for key in ("direct", "indirect", "no_edge")
        }
        top_value = max(classes.values())
        if top_value == 0:
            dominant = "unknown"
        else:
            winners = [key for key, value in classes.items() if value == top_value]
            dominant = winners[0] if len(winners) == 1 else "tie"

        candidates.append(
            {
                "pr_id": pr_id,
                "base_sha": record.get("recorded_base_sha"),
                "modified_tests_total": len(modified_tests),
                "modified_tests_resolved": len(modified_tests) - len(unresolved),
                "unresolved_tests": unresolved,
                "production_changes": production,
                "edge_candidates": edges,
                "no_edge_candidates": no_edge,
                "counts": dict(counts),
                "dominant_relation_candidate": dominant,
                "notes": notes,
            }
        )

    payload = {
        "schema_version": 1,
        "generated_by": "batch/case-analysis/tools/preclassify.py",
        "filters": {
            "classification": "MIXED_CODE_AND_TEST_PR",
            "production": "scrapy/**.py",
            "modified_tests": f"1..{MAX_MODIFIED_TESTS}",
        },
        "candidate_count": len(candidates),
        "excluded_count": len(excluded),
        "candidates": sorted(candidates, key=lambda item: item["pr_id"]),
        "excluded": excluded,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT} ({len(candidates)} candidates, {len(excluded)} excluded)")
    for item in payload["candidates"]:
        print(
            f"  pr{item['pr_id']}: dominant={item['dominant_relation_candidate']} "
            f"counts={item['counts']} tests={item['modified_tests_total']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
