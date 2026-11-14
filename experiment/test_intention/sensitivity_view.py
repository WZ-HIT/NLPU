"""TI-20: on-demand projection of saved facts, without new extraction or ranking."""
import json
from pathlib import Path
import tokenize

if __package__:
    from . import maintenance_view as maintenance, reader, search_view as search
else:
    import maintenance_view as maintenance
    import legacy_read as reader
    import search_view as search

VERSION = 'source-sensitivity-v1'
DIRECT = {
    'calls': 'api_or_construction_call',
    'assignments': 'assigned_value_or_configuration',
    'assertions': 'assertion_or_expected_value',
    'conditions': 'condition_or_iteration',
    'mock': 'mock_expression',
    'parameters': 'parameterization_or_decorator',
}
ASSOCIATED = {'annotations': 'type_annotation', 'inheritance': 'inheritance_source',
              'imports': 'import_reference', 'guards': 'import_guard',
              'context_calls': 'associated_definition_call'}


def points(root, db, identity):
    record = reader.load_test(db, identity)
    manifest = json.loads((root/'manifest.json').read_text())
    location = record['location']
    rows = []
    for section, kind in DIRECT.items():
        for i, fact in enumerate(record['facts'].get(section, [])):
            line = fact.get('line')
            if not isinstance(line, int) or not location['start_line'] <= line <= location['end_line']:
                raise ValueError('FACT_LOCATION_OUTSIDE_TEST')
            text = fact.get('expression', str(fact))
            ref = f'/facts/{section}/{i}'
            rows.append({'ref': ref, 'kind': kind, 'text': text,
                'scope': 'test_source_definition', 'owner': identity,
                'source': {'path': location['path'], 'start_line': line, 'end_line': line,
                           'file_sha256': manifest['source_files'][location['path']]},
                'source_extent': 'start line only; normalized expression may span more lines',
                'uncertainty': ['Saved syntax/candidate, not runtime execution or update necessity',
                                'Call syntax alone does not distinguish constructor from other callable'],
                'original_fact': fact})
    facts, coverage = maintenance.load(root, identity)
    for section, kind in ASSOCIATED.items():
        for i, fact in enumerate(facts[section]):
            rows.append({'ref': f'/maintenance/{section}/{i}', 'kind': kind, 'text': fact['text'],
                'scope': fact['scope'], 'owner': fact.get('owner'), 'source': fact['source'],
                'source_extent': 'saved syntax span; columns are UTF-8 byte offsets',
                'uncertainty': fact['uncertainty']+[fact['basis']], 'original_fact': fact})
    return rows, coverage


def short(row):
    text = row['text']
    return {'ref': row['ref'], 'kind': row['kind'], 'preview': text[:160],
            'truncated': len(text)>160, 'scope': row['scope'],
            'location': {k: row['source'][k] for k in ('path', 'start_line', 'end_line')},
            'uncertainty_count': len(row['uncertainty'])}


def expand(root, db, identity, ref, repository):
    rows, _ = points(root, db, identity)
    row = next((r for r in rows if r['ref']==ref), None)
    if row is None:
        raise ValueError('POINT_NOT_ASSOCIATED_WITH_TEST')
    location = row['source']
    relative = Path(location['path'])
    path = Path(repository)/relative
    base = Path(repository).resolve()
    if (relative.is_absolute() or '..' in relative.parts or
        not path.resolve().is_relative_to(base) or
        any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(Path(repository)))):
        raise ValueError('UNSAFE_POINT_SOURCE')
    if search.sha(path) != location['file_sha256']:
        raise ValueError('POINT_SOURCE_CHANGED')
    with tokenize.open(path) as stream:
        lines = stream.read().splitlines()
    start, end = location['start_line'], location['end_line']
    if not 1 <= start <= end <= len(lines):
        raise ValueError('INVALID_POINT_SPAN')
    return [dict(row, id=identity, source_lines=[{'line': i+1, 'source': lines[i]}
                                               for i in range(start-1, end)])]
