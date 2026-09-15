"""Pair changed pytest cases with changed focal methods."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_STOP_WORDS = {"test", "tests", "case", "with", "when", "should", "class", "method"}


def _leaf(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _tokens(value: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return {
        token.lower()
        for token in _TOKEN_RE.findall(expanded)
        if token.lower() not in _STOP_WORDS
    }


def _calls_name(calls: Iterable[str], target: str) -> bool:
    return any(call == target or call.endswith(f".{target}") for call in calls)


def _static_call_path(
    test_calls: Iterable[str],
    focal: dict[str, Any],
    supporting_definitions: list[dict[str, Any]],
) -> bool:
    """Return true for a direct call or a short call path through the changed module."""
    target = focal["name"]
    frontier = {_leaf(call) for call in test_calls}
    if target in frontier:
        return True
    definitions = {item["name"]: item for item in supporting_definitions}
    visited: set[str] = set()
    for _ in range(3):
        next_frontier: set[str] = set()
        for called_name in frontier - visited:
            visited.add(called_name)
            definition = definitions.get(called_name)
            if not definition:
                continue
            nested = {_leaf(call) for call in definition.get("calls", [])}
            if target in nested:
                return True
            next_frontier.update(nested)
        frontier = next_frontier
        if not frontier:
            break
    return False


def _module_match(test: dict[str, Any], focal: dict[str, Any]) -> bool:
    module = focal["file"][:-3].replace("/", ".")
    module_leaf = Path(focal["file"]).stem
    imports = set(test.get("imports", []))
    return any(
        item == module
        or item.endswith(f".{module_leaf}")
        or item == module_leaf
        for item in imports
    )


def _coverage_match(
    test: dict[str, Any], focal: dict[str, Any], coverage_map: dict[str, list[str]]
) -> bool:
    return focal["node_id"] in coverage_map.get(test["node_id"], [])


def _score_pair(
    test: dict[str, Any],
    focal: dict[str, Any],
    *,
    supporting_definitions: list[dict[str, Any]],
    coverage_map: dict[str, list[str]],
    file_order: dict[str, int],
) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    if _coverage_match(test, focal, coverage_map):
        score += 100
        evidence.append("coverage")
    if _calls_name(test.get("calls", []), focal["name"]):
        score += 60
        evidence.append("static_call")
    elif _static_call_path(test.get("calls", []), focal, supporting_definitions):
        score += 50
        evidence.append("static_call_path")
    if _module_match(test, focal):
        score += 20
        evidence.append("module_import")
    overlap = _tokens(test["qualified_name"]) & _tokens(focal["qualified_name"])
    if overlap:
        score += min(15, len(overlap) * 5)
        evidence.append("name_overlap")
    test_position = file_order.get(test["file"])
    focal_position = file_order.get(focal["file"])
    if test_position is not None and focal_position is not None:
        distance = abs(test_position - focal_position)
        if distance <= 1:
            score += 5
            evidence.append("diff_proximity")
    return score, evidence


def _sample_id(repo: str, pr_id: int, test_id: str, focal_id: str) -> str:
    identity = f"{repo}#{pr_id}:{test_id}:{focal_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    safe_repo = repo.replace("/", "__")
    return f"{safe_repo}__{pr_id}__{digest}"


def pair_changed_tests(
    repo: str,
    pr_id: int,
    focal_methods: list[dict[str, Any]],
    test_changes: list[dict[str, Any]],
    supporting_definitions: list[dict[str, Any]],
    changed_files: list[dict[str, Any]],
    *,
    coverage_map: dict[str, list[str]] | None = None,
    ci_status: str = "unknown",
) -> list[dict[str, Any]]:
    """Return one best focal-method pairing for every modified pytest case."""
    coverage_map = coverage_map or {}
    file_order = {
        item.get("filename", ""): index for index, item in enumerate(changed_files)
    }
    pairs: list[dict[str, Any]] = []

    for test in test_changes:
        if test.get("change_type") != "modified":
            continue
        ranked: list[tuple[int, str, dict[str, Any], list[str]]] = []
        for focal in focal_methods:
            score, evidence = _score_pair(
                test,
                focal,
                supporting_definitions=supporting_definitions,
                coverage_map=coverage_map,
                file_order=file_order,
            )
            ranked.append((score, focal["node_id"], focal, evidence))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        if not ranked:
            continue

        top_score, _, focal, evidence = ranked[0]
        tied = [item[2]["node_id"] for item in ranked if item[0] == top_score]
        behavior_evidence = {"coverage", "static_call", "static_call_path"}
        references_focal = bool(behavior_evidence.intersection(evidence))
        ambiguous = len(tied) > 1
        confidence = (
            "ambiguous"
            if ambiguous
            else "high"
            if references_focal
            else "medium"
            if top_score >= 20
            else "low"
        )
        reasons: list[str] = []
        if ambiguous:
            reasons.append("multiple focal methods have the same score")
        if not references_focal:
            reasons.append("gold test has no coverage or static call path to focal method")
        if ci_status != "success":
            reasons.append("PR head CI is not successful")
        eligibility = "accepted" if not reasons else "rejected"

        pairs.append(
            {
                "sample_id": _sample_id(
                    repo, pr_id, test["node_id"], focal["node_id"]
                ),
                "focal_method": focal,
                "test_change": test,
                "pair_score": top_score,
                "pair_confidence": confidence,
                "pair_evidence": evidence,
                "ambiguous_candidates": tied if ambiguous else [],
                "gold_validation": {
                    "gold_on_head": "pass" if ci_status == "success" else "unknown",
                    "gold_on_head_source": "pr_ci_rollup",
                    "gold_references_focal": references_focal,
                },
                "eligibility": eligibility,
                "rejection_reasons": reasons,
            }
        )
    return pairs
