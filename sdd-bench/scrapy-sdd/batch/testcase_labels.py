"""Host-only paired testcase labels; never import from the Agent stage runner."""
from __future__ import annotations
import ast
from collections import Counter
from typing import Any
from .core import canonical_sha256
from .testcase_identity import content_hash, function_ast, PROTOCOL


def build_labels(raw: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    by_id = {e['id']: e for e in index['entries']}
    included, excluded, issues = set(), [], []
    if raw.get('base_sha') != index['base_sha']:
        issues.append('BASE_MISMATCH')
    changes = raw.get('test_changes')
    if not isinstance(changes, list):
        changes = []
        issues.append('TEST_CHANGES_MISSING')
    for item in changes:
        path, qualified = item.get('file'), item.get('qualified_name')
        identity = f'{path}::{qualified}'
        kind = item.get('change_type')
        if kind in {'added', 'deleted', 'renamed'}:
            excluded.append({'id': identity, 'category': kind})
            continue
        if kind != 'modified':
            issues.append('UNKNOWN_CHANGE_TYPE')
            continue
        if identity not in by_id:
            # Helper/fixture and genuinely unresolvable test labels are distinct.
            leaf = qualified.split('.')[-1] if isinstance(qualified, str) else ''
            fixture = False
            try:
                before = function_ast(item.get('old_test', ''))
                decorators = [ast.unparse(d.func if isinstance(d, ast.Call) else d) for d in before.decorator_list]
                fixture = any(d.split('.')[-1] in {'fixture', 'fixturefunc'} for d in decorators)
            except (ValueError, TypeError, SyntaxError):
                pass
            category = 'helper_or_fixture' if fixture or not leaf.startswith('test') else 'UNRESOLVED_BASE_TEST'
            if category.isupper():
                issues.append(category)
            excluded.append({'id': identity, 'category': category})
            continue
        try:
            before = function_ast(item['old_test'])
            after = function_ast(item['gold_test'])
            if content_hash(before) != by_id[identity]['ast_sha256']:
                issues.append('OLD_SOURCE_MISMATCH')
                continue
            if before.name != after.name:
                excluded.append({'id': identity, 'category': 'renamed'})
            elif content_hash(before) == content_hash(after):
                excluded.append({'id': identity, 'category': 'mechanical_ast_equal'})
            else:
                included.add(identity)
        except (ValueError, TypeError, KeyError, SyntaxError):
            issues.append('UNPARSEABLE_TEST_CHANGE')
    document = {'schema_version': 1, 'document_type': 'HOST_TESTCASE_LABELS', 'protocol': PROTOCOL,
                'base_sha': index['base_sha'], 'index_sha256': index['index_sha256'],
                'raw_record_sha256': canonical_sha256(raw), 'testcases': sorted(included),
                'excluded': excluded, 'excluded_counts': dict(sorted(Counter(e['category'] for e in excluded).items())),
                'issues': sorted(set(issues)), 'complete': not issues and not index['errors']}
    document['labels_sha256'] = canonical_sha256(document)
    return document
