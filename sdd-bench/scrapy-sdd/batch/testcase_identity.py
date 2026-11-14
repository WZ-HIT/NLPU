"""Source-definition test identities. No gold access, imports or test execution.

The inventory is host-side validation data, never an extra Agent mount.
"""
from __future__ import annotations

import ast
import json
import tokenize
from pathlib import Path, PurePosixPath
from typing import Any

from .core import BatchError, canonical_sha256, sha256_file

PROTOCOL = 'testcase-v1'


def safe_test_path(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and '\\' not in value
            and not value.startswith('/') and '//' not in value
            and all(p not in {'.', '..'} for p in value.split('/'))
            and PurePosixPath(value).parts[0] in {'tests', 'test'} and value.endswith('.py'))


def function_ast(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    # Dedenting a method fragment also changes whitespace *inside* multiline
    # string constants. A wrapper preserves its exact Python semantics.
    try:
        body = ast.parse(source).body
    except IndentationError:
        wrapper = ast.parse('if True:\n' + source)
        body = wrapper.body[0].body
    if len(body) != 1 or not isinstance(body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError('Expected exactly one test definition')
    return body[0]


def content_hash(node: ast.AST) -> str:
    return canonical_sha256(ast.dump(node, include_attributes=False))


def inventory(repository: Path, base_sha: str) -> dict[str, Any]:
    """Index definitions, not pytest execution instances or inherited aliases."""
    entries, errors = [], []
    for folder in ('test', 'tests'):
        root = repository / folder
        if not root.exists():
            continue
        for path in sorted(root.rglob('*.py')):
            relative = path.relative_to(repository).as_posix()
            if path.is_symlink() or not path.resolve().is_relative_to(repository.resolve()):
                errors.append({'path': relative, 'code': 'UNSAFE_SOURCE'})
                continue
            try:
                with tokenize.open(path) as stream:
                    tree = ast.parse(stream.read(), filename=relative)
                file_sha = sha256_file(path)
            except (OSError, UnicodeError, SyntaxError):
                errors.append({'path': relative, 'code': 'SOURCE_UNREADABLE'})
                continue

            def collect(body: list[ast.stmt], scope: tuple[str, ...] = ()) -> None:
                for node in body:
                    if isinstance(node, ast.ClassDef):
                        collect(node.body, (*scope, node.name))
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        decorators = [ast.unparse(d.func if isinstance(d, ast.Call) else d) for d in node.decorator_list]
                        if not node.name.startswith('test') or any(d.split('.')[-1] in {'fixture', 'fixturefunc'} for d in decorators):
                            continue
                        # Nested helper functions are not separately collected.
                        qualified = '.'.join((*scope, node.name))
                        identity = relative + '::' + qualified
                        entries.append({'id': identity, 'path': relative, 'qualified_name': qualified,
                                        'start_line': min([node.lineno, *[d.lineno for d in node.decorator_list]]),
                                        'end_line': node.end_lineno, 'file_sha256': file_sha,
                                        'ast_sha256': content_hash(node)})
            collect(tree.body)
    entries.sort(key=lambda e: e['id'])
    if len({e['id'] for e in entries}) != len(entries):
        raise BatchError('TESTCASE_ID_AMBIGUOUS', 'Duplicate source definition identities')
    document = {'schema_version': 1, 'document_type': 'BASE_TESTCASE_INDEX',
                'protocol': PROTOCOL, 'base_sha': base_sha, 'entries': entries, 'errors': errors}
    document['index_sha256'] = canonical_sha256(document)
    return document


def resolve(candidates: list[dict[str, Any]], index: dict[str, Any]) -> dict[str, Any]:
    valid_ids = {e['id'] for e in index['entries']}
    predicted, invalid, files, duplicates = set(), set(), set(), 0
    for candidate in candidates:
        path = candidate.get('path')
        if safe_test_path(path):
            files.add(path)
        for symbol in candidate.get('symbols', []):
            identity = f'{path}::{symbol}'
            if identity in predicted or identity in invalid:
                duplicates += 1
            elif safe_test_path(path) and isinstance(symbol, str) and identity in valid_ids:
                predicted.add(identity)
            else:
                invalid.add(identity)
    return {'testcases': sorted(predicted), 'invalid': sorted(invalid),
            'files': sorted(files), 'duplicate_count': duplicates}


def verified_baseline(bench: Path, base: str) -> tuple[Path, dict[str, str]]:
    cache = bench / 'batch/baselines' / base
    lock_path = cache / 'baseline-lock.json'
    if lock_path.is_symlink():
        raise BatchError('TESTCASE_BASE_INVALID', 'Baseline lock is unsafe')
    lock = json.loads(lock_path.read_text())
    repo = cache / 'repository'
    if lock.get('base_sha') != base or lock.get('checkout_manifest_sha256') != canonical_sha256(lock['checkout_files']):
        raise BatchError('TESTCASE_BASE_INVALID', 'Baseline manifest identity is invalid')
    expected = {e['path']: e['sha256'] for e in lock['checkout_files'] if e['path'].endswith('.py') and e['path'].split('/')[0] in {'test','tests'}}
    actual = {p.relative_to(repo).as_posix(): sha256_file(p) for folder in ('test','tests') for p in (repo/folder).rglob('*.py') if p.is_file() and not p.is_symlink()}
    if actual != expected:
        raise BatchError('TESTCASE_BASE_CHANGED', 'Baseline test files differ from their lock')
    return repo, {'path': lock_path.relative_to(bench.parents[1]).as_posix(), 'sha256': sha256_file(lock_path)}

