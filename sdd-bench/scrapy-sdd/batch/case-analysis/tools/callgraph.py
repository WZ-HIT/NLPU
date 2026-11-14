"""Leaf-name call graph shared by the case-analysis tools.

Nodes are bare function leaf names, matching the convention in
``experiment/pair_tests.py``. That keeps the analysis consistent with existing
static evidence, but it also merges same-named definitions across modules, so
callers must report that ambiguity instead of presenting a path as exact.

No model, Docker, or network call is made.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable


def definition_calls(tree: ast.AST) -> dict[str, set[str]]:
    """Map leaf function name to the leaf names it calls."""
    calls: dict[str, set[str]] = defaultdict(set)

    def leaf(node: ast.AST) -> str | None:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = leaf(child.func)
                    if name:
                        calls[node.name].add(name.split(".")[-1])
    return calls


def build_graph(repo: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return a leaf-name call graph plus where each leaf name is defined.

    ``locations`` maps a leaf name to the repo-relative files defining it, so a
    consumer can tell whether a path node is unambiguous.
    """
    graph: dict[str, set[str]] = defaultdict(set)
    locations: dict[str, set[str]] = defaultdict(set)
    for root in (repo / "scrapy", repo / "tests"):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = str(path.relative_to(repo))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    locations[node.name].add(rel)
            for name, called in definition_calls(tree).items():
                graph[name].update(called)
    return graph, locations


def shortest_path(
    graph: dict[str, set[str]],
    starts: Iterable[str],
    target: str,
    max_depth: int = 8,
) -> list[str] | None:
    """Shortest call path from any start leaf to ``target``.

    Expansion is sorted so results are reproducible across runs; set iteration
    order would otherwise vary with ``PYTHONHASHSEED``.
    """
    start_names = sorted({name.split(".")[-1] for name in starts})
    if target in start_names:
        return [target]
    queue: deque[tuple[str, list[str]]] = deque((name, [name]) for name in start_names)
    seen = set(start_names)
    while queue:
        name, path = queue.popleft()
        if len(path) > max_depth:
            continue
        for callee in sorted(graph.get(name, ())):
            if callee == target:
                return [*path, callee]
            if callee not in seen:
                seen.add(callee)
                queue.append((callee, [*path, callee]))
    return None


def ambiguity_note(nodes: Iterable[str], locations: dict[str, set[str]]) -> str:
    """Describe path nodes whose leaf name is defined in several files."""
    ambiguous = [
        f"{name} ({len(locations[name])} defs)"
        for name in nodes
        if len(locations.get(name, ())) > 1
    ]
    if not ambiguous:
        return ""
    return (
        " Leaf-name call graph cannot disambiguate: "
        + ", ".join(ambiguous)
        + "; confirm the module-level path during review."
    )
