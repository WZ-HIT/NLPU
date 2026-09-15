"""Extract changed Python functions and pytest cases from base/head checkouts."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from demo_pipeline import is_test_file


@dataclass(frozen=True)
class Definition:
    file: str
    qualified_name: str
    name: str
    kind: str
    source: str
    start_line: int
    end_line: int
    decorators: tuple[str, ...]
    calls: tuple[str, ...]
    imports: tuple[str, ...]

    @property
    def node_id(self) -> str:
        return f"{self.file}::{self.qualified_name}"

    @property
    def source_hash(self) -> str:
        return hashlib.sha256(self.source.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "node_id": self.node_id, "source_hash": self.source_hash}


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    return _dotted_name(node) or type(node).__name__


def _file_imports(tree: ast.Module) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.add(alias.name)
                result.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                result.add(node.module)
            for alias in node.names:
                result.add(alias.name)
                result.add(alias.asname or alias.name)
    return result


def _calls(node: ast.AST) -> set[str]:
    result: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _dotted_name(child.func)
            if name:
                result.add(name)
    return result


class _Collector(ast.NodeVisitor):
    def __init__(self, source: str, filename: str, imports: set[str]) -> None:
        self.lines = source.splitlines()
        self.filename = filename
        self.imports = imports
        self.scope: list[str] = []
        self.definitions: list[Definition] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node, "function" if not self.scope else "method")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        kind = "async_function" if not self.scope else "async_method"
        self._record_function(node, kind)

    def _record_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str
    ) -> None:
        decorator_lines = [item.lineno for item in node.decorator_list]
        start_line = min([node.lineno, *decorator_lines])
        end_line = node.end_lineno or node.lineno
        qualified_name = ".".join([*self.scope, node.name])
        source = "\n".join(self.lines[start_line - 1 : end_line])
        self.definitions.append(
            Definition(
                file=self.filename,
                qualified_name=qualified_name,
                name=node.name,
                kind=kind,
                source=source,
                start_line=start_line,
                end_line=end_line,
                decorators=tuple(_decorator_name(item) for item in node.decorator_list),
                calls=tuple(sorted(_calls(node))),
                imports=tuple(sorted(self.imports)),
            )
        )
        self.scope.append(node.name)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)
        self.scope.pop()


def extract_definitions(source: str, filename: str) -> list[Definition]:
    """Parse all top-level functions, methods, and nested definitions in source."""
    tree = ast.parse(source, filename=filename)
    collector = _Collector(source, filename, _file_imports(tree))
    collector.visit(tree)
    return collector.definitions


def _safe_source(root: Path, filename: str) -> str | None:
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe repository path: {filename}")
    path = root / relative
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _is_pytest_definition(definition: Definition) -> bool:
    return definition.name.startswith("test")


def _change(
    before: Definition | None, after: Definition | None, change_type: str
) -> dict[str, Any]:
    representative = after or before
    assert representative is not None
    return {
        "node_id": representative.node_id,
        "file": representative.file,
        "qualified_name": representative.qualified_name,
        "name": representative.name,
        "kind": representative.kind,
        "change_type": change_type,
        "before_source": before.source if before else "",
        "after_source": after.source if after else "",
        "before_hash": before.source_hash if before else "",
        "after_hash": after.source_hash if after else "",
        "start_line": after.start_line if after else before.start_line,
        "end_line": after.end_line if after else before.end_line,
        "decorators": list((after or before).decorators),
        "calls": list((after or before).calls),
        "imports": list((after or before).imports),
    }


def compare_definitions(
    before: Iterable[Definition], after: Iterable[Definition]
) -> list[dict[str, Any]]:
    before_by_name = {item.qualified_name: item for item in before}
    after_by_name = {item.qualified_name: item for item in after}
    changes: list[dict[str, Any]] = []
    for name in sorted(before_by_name.keys() | after_by_name.keys()):
        old = before_by_name.get(name)
        new = after_by_name.get(name)
        if old and new and old.source_hash == new.source_hash:
            continue
        change_type = "modified" if old and new else "added" if new else "deleted"
        changes.append(_change(old, new, change_type))
    return changes


def extract_changed_definitions(
    base_root: Path,
    head_root: Path,
    changed_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract method-level production and test changes from complete checkouts."""
    focal_methods: list[dict[str, Any]] = []
    test_changes: list[dict[str, Any]] = []
    supporting_definitions: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for file_info in changed_files:
        filename = file_info.get("filename", "")
        if not filename.endswith(".py"):
            continue
        try:
            before_source = _safe_source(base_root, filename)
            after_source = _safe_source(head_root, filename)
            before = extract_definitions(before_source, filename) if before_source else []
            after = extract_definitions(after_source, filename) if after_source else []
        except (SyntaxError, OSError, UnicodeError, ValueError) as exc:
            errors.append({"file": filename, "error": str(exc)})
            continue

        changes = compare_definitions(before, after)
        if is_test_file(filename):
            for item in changes:
                representative = next(
                    (
                        definition
                        for definition in [*after, *before]
                        if definition.qualified_name == item["qualified_name"]
                    ),
                    None,
                )
                if representative and _is_pytest_definition(representative):
                    old_test = item.pop("before_source")
                    gold_test = item.pop("after_source")
                    test_changes.append(
                        {
                            **item,
                            "old_test": old_test,
                            "gold_test": gold_test,
                        }
                    )
        else:
            focal_methods.extend(
                item for item in changes if item["change_type"] in {"modified", "added"}
            )
            supporting_definitions.extend(item.to_dict() for item in after)

    return {
        "focal_methods": focal_methods,
        "test_changes": test_changes,
        "supporting_definitions": supporting_definitions,
        "errors": errors,
    }
