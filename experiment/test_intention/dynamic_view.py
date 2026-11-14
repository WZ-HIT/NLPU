"""D-group runtime views. Stdlib only; independent of collector/host evaluation."""
from collections import defaultdict, deque
import json
from pathlib import Path
import sqlite3

VERSION = 'dynamic-intention-v1'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def connect(root):
    path = root / '.dynamic.sqlite3'
    if path.is_symlink() or not path.is_file():
        raise ValueError('DYNAMIC_DATABASE_MISSING_OR_UNSAFE')
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)


def execution_paths(document):
    """Shortest root paths per actual instance; never traverse the union graph."""
    valid = {i['execution_id'] for i in document['instances'] if i['evidence_status'] == 'valid'}
    edges = {i: defaultdict(set) for i in valid}
    for edge in document['edges']:
        support = edge.get('supporting_instances')
        if not support or not set(support) <= valid:
            raise ValueError('INVALID_EDGE_INSTANCE_PROVENANCE')
        for instance in support:
            edges[instance][edge['caller']].add(edge['callee'])
    result = {}
    for instance, graph in sorted(edges.items()):
        root = document['source_test_id']
        paths = {root: [root]}
        pending = deque([root])
        while pending:
            caller = pending.popleft()
            for callee in sorted(graph[caller]):
                if callee not in paths:
                    paths[callee] = [*paths[caller], callee]
                    pending.append(callee)
        result[instance] = paths
    return result


def shortest_paths(document):
    result = {}
    for instance, paths in execution_paths(document).items():
        for function, nodes in paths.items():
            candidate = {'execution_id': instance, 'nodes': nodes}
            previous = result.get(function)
            if previous is None or (len(nodes), instance, nodes) < (
                    len(previous['nodes']), previous['execution_id'], previous['nodes']):
                result[function] = candidate
    return result


def metadata(db, identity):
    row = db.execute('SELECT status,expected,valid,production_count,shallow_count,graph FROM methods WHERE id=?',
                     (identity,)).fetchone()
    if row is None:
        raise ValueError('UNKNOWN_SOURCE_TEST_ID')
    status, expected, valid, count, shallow, graph = row
    return {'coverage_status': status, 'expected_instances': expected, 'valid_instances': valid,
            'production_function_count': count, 'depth_le_2_function_count': shallow,
            'provided': status == 'complete',
            'scope': 'test body; method-level observations, not scenario attribution',
            'coverage_read': 'coverage ' + identity if graph else None,
            'graph_read': 'trace ' + identity if graph else None,
            'shared_read': 'shared ' + identity if graph else None}


def graph_document(root, db, identity):
    info = metadata(db, identity)
    if not info['provided']:
        return info, None
    relative, = db.execute('SELECT graph FROM methods WHERE id=?', (identity,)).fetchone()
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('UNSAFE_GRAPH_PATH')
    document = json.loads(path.read_text())
    if document['source_test_id'] != identity or document['coverage_status'] != 'complete':
        raise ValueError('GRAPH_IDENTITY_OR_STATUS_CHANGED')
    return info, document


def coverage_rows(db, identity):
    info = metadata(db, identity)
    if not info['provided']:
        return [{'id': identity, **info, 'reason': 'Complete dynamic evidence not provided; relation unknown'}]
    return [{'function': f, 'minimum_root_depth': depth, 'path': json.loads(path) if path else None,
             'covered_but_root_unreachable': depth is None}
            for f, depth, path in db.execute('SELECT function,depth,path FROM coverage WHERE test_id=? ORDER BY function',
                                             (identity,))]


def trace_rows(root, db, identity, depth=2, instance=None):
    info, document = graph_document(root, db, identity)
    if document is None:
        return [{'id': identity, **info, 'reason': 'Complete dynamic evidence not provided; relation unknown'}]
    paths = execution_paths(document)
    if instance is not None and instance not in paths:
        raise ValueError('UNKNOWN_VALID_EXECUTION_ID')
    rows = [{'id': identity, **info, 'depth_limit': depth or 'full',
             'graph_scope': 'Each instance graph is separate; edges never imply a cross-instance path',
             'full_read': 'trace ' + identity + ' --depth 0',
             'instance_count': len(paths)}]
    if not depth:
        rows.extend({'method_observed_node': node, 'scope': 'All valid instances of this method; not a root path'}
                    for node in document['nodes'])
    for execution, reached in paths.items():
        if instance is not None and execution != instance:
            continue
        selected = {node for node, path in reached.items() if not depth or len(path)-1 <= depth}
        edges = [e for e in document['edges'] if execution in e['supporting_instances'] and
                 (not depth or e['caller'] in selected and e['callee'] in selected)]
        nodes = {n['id'] for n in document['nodes'] if not depth and any(
            n['id'] == e['caller'] or n['id'] == e['callee'] for e in edges)} | selected
        # Isolated production coverage is listed by coverage, not invented as a root edge.
        rows.append({'execution_id': execution, 'root': identity, 'visible_nodes': len(nodes),
                     'visible_edges': len(edges), 'reachable_nodes': len(reached)})
        rows.extend({'execution_id': execution, 'node': node,
                     'root_depth': len(reached[node])-1 if node in reached else None}
                    for node in sorted(nodes))
        rows.extend({'execution_id': execution, 'caller': e['caller'], 'callee': e['callee'],
                     'kind': e['kind'], 'basis': 'observed Python parent in this execution'} for e in edges)
        if not depth:
            rows.extend({'execution_id': execution, 'external_boundary': b}
                        for b in document.get('external_boundaries', []) if execution in b['supporting_instances'])
    return rows


def witness_rows(db, identity, other):
    if not metadata(db, identity)['provided'] or not metadata(db, other)['provided']:
        return []
    return [{'function': f, 'covering_complete_test_count': frequency,
             'source_depth': da, 'target_depth': db_depth,
             'source_path': json.loads(pa), 'target_path': json.loads(pb)}
            for f, da, db_depth, pa, pb, frequency in db.execute('''
                SELECT a.function,a.depth,b.depth,a.path,b.path,f.tests
                FROM coverage a JOIN coverage b ON a.function=b.function
                JOIN frequencies f ON f.function=a.function
                WHERE a.test_id=? AND b.test_id=? AND a.depth<=2 AND b.depth<=2
                ORDER BY f.tests,a.function''', (identity, other))]


def shared_rows(db, evidence, identity, other=None):
    info = metadata(db, identity)
    if not info['provided']:
        return [{'id': identity, **info, 'reason': 'Complete dynamic evidence not provided; relation unknown'}]
    if other is not None:
        if other == identity:
            raise ValueError('SHARED_QUERY_REQUIRES_DIFFERENT_TESTS')
        target = metadata(db, other)
        if not target['provided']:
            return [{'id': other, **target, 'reason': 'Complete dynamic evidence not provided; relation unknown'}]
        return witness_rows(db, identity, other)
    neighbors = db.execute('''
        SELECT b.test_id,COUNT(*),MIN(f.tests)
        FROM coverage a JOIN coverage b ON a.function=b.function
        JOIN frequencies f ON f.function=a.function
        WHERE a.test_id=? AND b.test_id!=? AND a.depth<=2 AND b.depth<=2
        GROUP BY b.test_id ORDER BY MIN(f.tests),COUNT(*) DESC,b.test_id''', (identity, identity)).fetchall()
    rows = []
    for target, count, rarest in neighbors:
        record = evidence.execute('SELECT card,intention FROM tests WHERE id=?', (target,)).fetchone()
        intention = json.loads(record[1]) or {}
        goal = intention.get('summary')
        witnesses = witness_rows(db, identity, target)
        rows.append({'id': target, 'relation': 'shared_production_within_depth_2',
                     'source_status': 'complete', 'target_status': 'complete',
                     'goal_preview': goal[:120] if goal else None,
                     'goal_more': bool(goal and len(goal) > 120),
                     'goal_read': 'detail ' + target + ' --field summary' if goal else None,
                     'shared_function_count': count, 'lowest_covering_test_count': rarest,
                     'witness': witnesses[0], 'additional_witnesses': count-1,
                     'witnesses_read': 'shared ' + identity + ' --with ' + target,
                     'ti_read': 'show ' + target, 'source_read': 'source ' + target,
                     'basis': 'Observed shared production call; update necessity requires task and assertion evidence'})
    return rows
