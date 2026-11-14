"""Offline D export: unchanged frozen C plus complete-only, base-pinned traces."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sqlite3

from . import dynamic_view, reader, search_view
from .stage_b_bundle import checked, write
from test_trace.common import file_hash, read_json
from test_trace.query import safe_file

FORMAT = 'dynamic-intention-v1'
GUIDE = '''

## D: observed runtime evidence and two-layer test relationships

This is C plus independent method-level dynamic facts. Existing semantic/static
records, search fields, ranking and source identities are unchanged. show adds
dynamic status/counts/reading entrances. Existing relations/neighbors remain STATIC.
Only complete methods provide runtime data. Partial/unavailable/not_discovered
methods remain searchable through their original TI; no coverage/graph for them is
included. Missing runtime evidence is UNKNOWN, never zero coverage or irrelevance.
Complete means all discovered executions passed body/identity validation in this
environment, not every possible input/branch. Capture covers TEST BODIES only,
excluding fixture/setup/teardown. Call/coverage does not establish assertion dependence.

    python3 test-intentions/read.py show 'TEST_ID'
    python3 test-intentions/read.py coverage 'TEST_ID'
    python3 test-intentions/read.py trace 'TEST_ID'
    python3 test-intentions/read.py trace 'TEST_ID' --depth 0
    python3 test-intentions/read.py trace 'TEST_ID' --instance 'EXECUTION_ID'
    python3 test-intentions/read.py shared 'TEST_ID'
    python3 test-intentions/read.py shared 'TEST_ID' --with 'OTHER_TEST_ID'

Trace defaults to two layers; --depth 0 expands the full saved graph, paged rather
than dumped. Paths are computed separately for each valid execution. Never splice
edges from different instances. Root-unreachable covered functions remain visible
in coverage but do not qualify as shallow. shared requires the SAME production
function at root distance <=2 in BOTH complete tests. Each witness gives each
side's own execution ID and observed path; it does not claim simultaneous execution.

When task/TI/source evidence suggests a test may need updating, consider querying
its shared tests, then inspect their TI and assertions for overlooked behaviors.
Seeds are your current candidates, not known-correct answers. A relationship is an
investigation lead, never an instruction to select a test. All existing tests remain
independently searchable. No automatic recursive expansion or production stage.

Neighbors sort by lowest covering-complete-test count among shared functions, then
shared function count descending, then source ID. Frequency counts distinct complete
TI methods in this base over their full production coverage, not calls or labels.
The first witness is a preview; additional_witnesses and witnesses_read expose the
rest. --with reads all witnesses. Continue using --offset next_offset. Page defaults
and explicit fragment rules are identical to C; no permanent neighbor cutoff.
'''


def export(source, trace_root, destination, trace_sha256=None):
    parent = checked(source)
    if parent.get('material_group') != 'C' or parent.get('representation_format') != 'matched-intention-v1':
        raise ValueError('D_REQUIRES_FROZEN_C')
    mp = trace_root / 'manifest.json'
    if trace_root.is_symlink() or mp.is_symlink():
        raise ValueError('UNSAFE_TRACE_MANIFEST')
    if trace_sha256 and file_hash(mp) != trace_sha256:
        raise ValueError('TRACE_MANIFEST_CHANGED')
    trace = read_json(mp)
    if trace['base_sha'] != parent['base_sha'] or trace['collection_scope'] != 'test_body_only':
        raise ValueError('TRACE_BASE_OR_SCOPE_MISMATCH')
    if any(trace['source_files'].get(p) != h for p, h in parent['source_files'].items()):
        raise ValueError('C_TRACE_SOURCE_MISMATCH')

    def saved(relative):
        path = safe_file(trace_root, relative)
        if file_hash(path) != trace['files'][relative]:
            raise ValueError('TRACE_FILE_CHANGED: ' + relative)
        return read_json(path)

    index = saved('index.json')
    if index['snapshot_id'] != trace['snapshot_id'] or index['base_sha'] != parent['base_sha']:
        raise ValueError('TRACE_INDEX_PROVENANCE_MISMATCH')
    entries = {e['id']: e for e in index['tests']}
    if len(entries) != len(index['tests']):
        raise ValueError('DUPLICATE_TRACE_ID')
    with reader.connect(source) as original:
        identities = [r[0] for r in original.execute('SELECT id FROM tests ORDER BY id')]
    if len(identities) != parent['test_count']:
        raise ValueError('C_INVENTORY_COUNT_MISMATCH')
    if destination.exists():
        raise ValueError('Refusing overwrite')
    shutil.copytree(source, destination)
    (destination / 'manifest.json').unlink()
    shutil.copyfile(source / 'read.py', destination / 'ti_read.py')
    for name, target in [('dynamic_reader.py', 'read.py'), ('dynamic_view.py', 'dynamic_view.py')]:
        shutil.copyfile(Path(__file__).with_name(name), destination / target)
    (destination / 'dynamic').mkdir()
    statuses, frequency = Counter(), Counter()
    coverage_rows = []
    with sqlite3.connect(destination / '.dynamic.sqlite3') as db:
        db.executescript('''
            CREATE TABLE methods(id TEXT PRIMARY KEY,status TEXT,expected INTEGER,valid INTEGER,
                                 production_count INTEGER,shallow_count INTEGER,graph TEXT);
            CREATE TABLE coverage(test_id TEXT,function TEXT,depth INTEGER,path TEXT,
                                  PRIMARY KEY(test_id,function));
            CREATE INDEX coverage_function ON coverage(function,depth,test_id);
            CREATE TABLE frequencies(function TEXT PRIMARY KEY,tests INTEGER);
        ''')
        for identity in identities:
            entry = entries.get(identity)
            status = entry['coverage_status'] if entry else 'not_discovered'
            statuses[status] += 1
            expected = entry['expected_instances'] if entry else None
            valid = entry['valid_instances'] if entry else 0
            graph = count = shallow = None
            if status == 'complete':
                document = saved(entry['path'])
                if (document['source_test_id'] != identity or document['coverage_status'] != 'complete'
                        or document['valid_instances'] != document['expected_instances']
                        or document['expected_instances'] != expected
                        or len(document['instances']) != expected
                        or not document['valid_instances'] or document['valid_instances'] != valid
                        or any(i['evidence_status'] != 'valid' or i['outcome'] != 'passed'
                               for i in document['instances'])):
                    raise ValueError('INVALID_COMPLETE_TRACE')
                production = document['production_covered_functions']
                if production is None:
                    raise ValueError('COMPLETE_COVERAGE_IS_NULL')
                paths = dynamic_view.shortest_paths(document)
                count = len(set(production))
                shallow = sum(f in paths and len(paths[f]['nodes'])-1 <= 2 for f in set(production))
                for function in sorted(set(production)):
                    path = paths.get(function)
                    coverage_rows.append((identity, function, len(path['nodes'])-1 if path else None,
                                          dynamic_view.encoded(path) if path else None))
                frequency.update(set(production))
                graph = 'dynamic/' + search_view.sha(safe_file(trace_root, entry['path'])) + '.json'
                shutil.copyfile(safe_file(trace_root, entry['path']), destination / graph)
            elif status not in {'partial', 'unavailable', 'not_discovered'}:
                raise ValueError('UNKNOWN_COVERAGE_STATUS')
            db.execute('INSERT INTO methods VALUES(?,?,?,?,?,?,?)',
                       (identity, status, expected, valid, count, shallow, graph))
        db.executemany('INSERT INTO coverage VALUES(?,?,?,?)', coverage_rows)
        db.executemany('INSERT INTO frequencies VALUES(?,?)', sorted(frequency.items()))
    (destination / 'README.md').write_text((source / 'README.md').read_text() + GUIDE)
    (destination / '.rgignore').write_text((source / '.rgignore').read_text() +
                                         '\n.dynamic.sqlite3\ndynamic/\ndynamic_view.py\nti_read.py\n')
    preserved = {p: h for p, h in parent['files'].items() if p not in {'README.md', '.rgignore', 'read.py'}}
    if any(file_hash(destination / p) != h for p, h in preserved.items()):
        raise ValueError('ORIGINAL_C_CHANGED')
    manifest = dict(parent, representation_format=FORMAT, material_group='D',
                    c_parent_manifest_sha256=file_hash(source / 'manifest.json'),
                    trace_manifest_sha256=file_hash(mp), trace_snapshot_id=trace['snapshot_id'],
                    trace_environment_id=trace['environment_id'], dynamic_status_counts=dict(statuses),
                    dynamic_contract={'provided': 'complete_only', 'level': 'source_method',
                                      'depth': 'per-valid-instance BFS, then minimum', 'shared_depth': 2,
                                      'search': 'unchanged C index and fields',
                                      'frequency': 'distinct complete TI methods covering each production function'})
    manifest['files'] = {p.relative_to(destination).as_posix(): file_hash(p)
                         for p in sorted(destination.rglob('*')) if p.is_file()}
    write(destination / 'manifest.json', manifest)
    checked(destination)
    return {'base_sha': parent['base_sha'], 'tests': len(identities), 'statuses': dict(statuses),
            'coverage_memberships': len(coverage_rows), 'production_functions': len(frequency),
            'preserved_C_files': len(preserved), 'search_index_unchanged': True,
            'manifest_sha256': file_hash(destination / 'manifest.json'),
            'c_parent_manifest_sha256': file_hash(source / 'manifest.json'),
            'trace_manifest_sha256': file_hash(mp)}


def run(scope_path, c_materials, trace_artifacts, output):
    if output.exists():
        raise ValueError('Use a new D publication directory')
    plan = read_json(scope_path)
    pairs = sorted({(t['task_id'], t['base_sha']) for t in plan['targets']})
    if len({t for t, b in pairs}) != len(pairs):
        raise ValueError('TASK_BASE_AMBIGUOUS')
    artifacts = read_json(trace_artifacts)['artifacts']
    output.mkdir(parents=True)
    write(output / 'scope.json', {'tasks': [{'task_id': t, 'base_sha': b} for t, b in pairs],
                                  'group': 'D', 'models': 0, 'new_test_executions': 0,
                                  'source_scope_sha256': file_hash(scope_path)})
    rows = []
    for base in sorted({b for t, b in pairs}):
        ref = artifacts[base]
        row = export(c_materials / base, Path(ref['path']).parent,
                     output / 'materials' / 'D' / base, ref['sha256'])
        rows.append(row)
        write(output / 'progress.json', {'completed_bases': len(rows), 'total_bases': len({b for t, b in pairs}), 'last': row})
        print(json.dumps(row), flush=True)
    write(output / 'materials.json', {'group': 'D', 'format': FORMAT, 'bases': rows,
                                     'prs': len(pairs), 'new_models': 0, 'new_test_executions': 0,
                                     'sources': {str(p): file_hash(p) for p in (scope_path, trace_artifacts)}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', type=Path, required=True, help='Existing C task/base plan, no labels')
    parser.add_argument('--c-materials', type=Path, required=True)
    parser.add_argument('--trace-artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.scope.resolve(), args.c_materials.resolve(), args.trace_artifacts.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
