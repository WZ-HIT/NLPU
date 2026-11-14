"""Resolve executed Python code to definitions in an allowed source snapshot.

This module does not import the analyzed project. Runtime source aliases are
accepted only when both files have identical bytes.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import tokenize
from pathlib import Path
from types import CodeType
from typing import Any


class SymbolIndex:
    def __init__(self, repository_root: str | Path, production_roots=(), source_mappings=(), source_files=None):
        self.root = Path(repository_root).resolve()
        self.production_roots = tuple(Path(p).as_posix().rstrip('/') for p in production_roots)
        self.mappings = []
        for entry in source_mappings:
            target = Path(entry['repository_root'])
            if not target.is_absolute():
                target = self.root / target
            target = target.resolve()
            if not target.is_relative_to(self.root):
                raise ValueError('Source mapping destination is outside repository_root')
            self.mappings.append((Path(entry['runtime_root']).resolve(), target))
        self.mappings.sort(key=lambda pair: len(str(pair[0])), reverse=True)
        self.errors: list[dict[str, str]] = []
        self.source_files = source_files
        self.limitations: set[str] = set()
        self.excluded_sources: dict[str, dict[str, str]] = {}
        self.test_ids: set[str] = set()
        self.test_paths: set[str] = set()
        self._paths: dict[str, Path | None] = {}
        self._definitions: dict[Path, list[dict[str, Any]]] = {}
        # CodeType equality deliberately ignores co_filename. Keep identity
        # keys and strong references so equal code in different files cannot
        # borrow another file's symbol, nor can a recycled id hit this cache.
        self._symbols: dict[int, tuple[CodeType, dict[str, Any] | None]] = {}

    def register_test_ids(self, identities) -> None:
        self.test_ids.update(identity for identity in identities if isinstance(identity, str))
        self.test_paths.update(identity.split('::', 1)[0] for identity in self.test_ids)
        for _, symbol in self._symbols.values():
            if symbol is not None and symbol['path'] in self.test_paths:
                symbol['kind'] = 'test'

    def source_path(self, filename: str) -> Path | None:
        if filename in self._paths:
            cached = self._paths[filename]
            return cached if cached is None or self._validate_snapshot(cached) else None
        result = None
        if filename and not filename.startswith('<'):
            runtime = Path(filename).resolve()
            mapped = False
            # Explicit mappings also take precedence when an environment is
            # located at repository/.venv, outside the snapshot whitelist.
            for origin, target in self.mappings:
                if not runtime.is_relative_to(origin):
                    continue
                mapped = True
                expected = (target / runtime.relative_to(origin)).resolve()
                if (runtime.suffix == '.py' and expected.is_relative_to(self.root)
                        and runtime.is_file() and expected.is_file()):
                    if hashlib.sha256(runtime.read_bytes()).digest() == hashlib.sha256(expected.read_bytes()).digest():
                        result = expected
                    else:
                        self.errors.append({'code': 'SOURCE_MAPPING_CONTENT_MISMATCH', 'runtime_path': str(runtime),
                                            'repository_path': expected.relative_to(self.root).as_posix()})
                break
            if not mapped and runtime.is_relative_to(self.root) and runtime.suffix == '.py' and runtime.is_file():
                result = runtime
        self._paths[filename] = result
        return result if result is None or self._validate_snapshot(result) else None

    def _validate_snapshot(self, path: Path) -> bool:
        if self.source_files is None:
            return True
        relative = path.relative_to(self.root).as_posix()
        expected = self.source_files.get(relative)
        if expected is None:
            self.limitations.add('generated_or_non_snapshot_sources_excluded')
            self.excluded_sources[relative] = {'path': relative, 'reason': 'SOURCE_NOT_IN_SNAPSHOT'}
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            error = {'code': 'SOURCE_CONTENT_CHANGED', 'path': relative}
            if error not in self.errors:
                self.errors.append(error)
            self.excluded_sources[relative] = {'path': relative, 'reason': 'SOURCE_CONTENT_CHANGED'}
            return False
        return True

    def definitions(self, path: Path) -> list[dict[str, Any]]:
        if path in self._definitions:
            return self._definitions[path]
        entries: list[dict[str, Any]] = []
        try:
            with tokenize.open(path) as stream:
                tree = ast.parse(stream.read(), filename=str(path))
            def visit(node: ast.AST, scope: tuple[str, ...] = ()) -> None:
                for child in ast.iter_child_nodes(node):
                    nested_scope = scope
                    if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        nested_scope = (*scope, child.name)
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            entries.append({'qualified_name': '.'.join(nested_scope),
                                            'start_line': child.lineno, 'end_line': child.end_lineno,
                                            'code_start_line': min([child.lineno, *[d.lineno for d in child.decorator_list]]),
                                            'is_async': isinstance(child, ast.AsyncFunctionDef),
                                            'is_fixture': any((ast.unparse(d.func if isinstance(d, ast.Call) else d).split('.')[-1]
                                                               in {'fixture', 'fixturefunc'}) for d in child.decorator_list)})
                    visit(child, nested_scope)
            visit(tree)
        except (OSError, UnicodeError, SyntaxError) as exc:
            self.errors.append({'code': 'SOURCE_UNREADABLE', 'path': str(path), 'detail': type(exc).__name__})
        self._definitions[path] = entries
        return entries

    def resolve(self, code: CodeType) -> dict[str, Any] | None:
        if id(code) in self._symbols:
            return self._symbols[id(code)][1]
        result = None
        path = self.source_path(code.co_filename)
        if path is not None:
            qualified = getattr(code, 'co_qualname', code.co_name).replace('.<locals>.', '.')
            candidates = [d for d in self.definitions(path)
                          if d['qualified_name'] == qualified and d['code_start_line'] == code.co_firstlineno]
            # Python <3.11 does not expose co_qualname. A unique definition at
            # the code's starting line is still sufficient; names alone are not.
            if not hasattr(code, 'co_qualname'):
                candidates = [d for d in self.definitions(path)
                              if d['code_start_line'] == code.co_firstlineno and d['qualified_name'].split('.')[-1] == code.co_name]
            if len(candidates) == 1:
                definition = candidates[0]
                relative = path.relative_to(self.root).as_posix()
                production = any(prefix in {'', '.'} or relative == prefix or relative.startswith(prefix + '/') for prefix in self.production_roots)
                kind = 'production' if production else 'project_support'
                if (relative in self.test_paths or any(p in {'test', 'tests'} for p in Path(relative).parts)
                        or Path(relative).name.startswith('test_') or Path(relative).name.endswith('_test.py')
                        or Path(relative).name == 'conftest.py' or definition['is_fixture']):
                    kind = 'test'
                result = {'id': relative + '::' + definition['qualified_name'], 'path': relative,
                          'qualified_name': definition['qualified_name'], 'start_line': definition['start_line'],
                          'end_line': definition['end_line'], 'kind': kind, 'is_async': definition['is_async']}
        self._symbols[id(code)] = (code, result)
        return result

    def resolve_callable(self, obj: Any) -> dict[str, Any]:
        try:
            underlying = inspect.unwrap(obj)
            underlying = getattr(underlying, '__func__', underlying)
            code = getattr(underlying, '__code__', None)
            symbol = self.resolve(code) if isinstance(code, CodeType) else None
        except (ValueError, TypeError, OSError) as exc:
            return {'source_test_id': None, 'source_identity_status': 'unknown', 'identity_error': type(exc).__name__}
        if symbol is None:
            return {'source_test_id': None, 'source_identity_status': 'unknown'}
        return {'source_test_id': symbol['id'], 'source_identity_status': 'verified',
                'path': symbol['path'], 'qualified_name': symbol['qualified_name'],
                'start_line': symbol['start_line'], 'is_async': symbol['is_async']}

