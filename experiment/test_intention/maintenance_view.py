"""Public, stdlib-only views of new base-derived facts. No host evaluator imports."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tokenize

if __package__:
    from . import search_view as search
else:
    import search_view as search

VERSION = 'maintenance-view-v1'
CATEGORIES = ('annotations', 'inheritance', 'context_calls', 'imports', 'guards')
EXTRA_FIELDS = tuple('maintenance.'+c for c in CATEGORIES)


def connect(root):
    path = root/'.maintenance.sqlite3'
    if path.is_symlink() or not path.is_file():
        raise ValueError('MAINTENANCE_DATABASE_UNSAFE')
    return sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1', uri=True)


def load(root, identity):
    with connect(root) as db:
        row = db.execute('SELECT metadata FROM coverage WHERE test_id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Unknown source test ID')
        facts = {c: [] for c in CATEGORIES}
        for category, raw in db.execute('SELECT m.category,f.record FROM members m JOIN facts f ON m.fact_id=f.id WHERE m.test_id=? ORDER BY m.category,m.ordinal', (identity,)):
            facts[category].append(json.loads(raw))
    return facts, json.loads(row[0])


def fields(facts):
    result = []
    for category in CATEGORIES:
        for i, fact in enumerate(facts[category]):
            ref = '/maintenance/'+category+'/'+str(i)
            result.append({'field': 'maintenance.'+category, 'ref': ref+'/text', 'text': fact['text'],
                           'origin': 'new source syntax; associated context does not prove execution'})
            for j, target in enumerate(fact['targets']):
                result.append({'field': 'maintenance.'+category, 'ref': ref+'/targets/'+str(j), 'text': target,
                               'origin': 'derived static target or import binding candidate'})
    return result


def rank(documents, stats, queries, *, mode='or', selected=(), file=None, sort='field-bm25-v1'):
    allowed = (*search.FIELDS, *EXTRA_FIELDS)
    if sort not in search.SORTS or mode not in ('or','and') or any(f not in allowed for f in selected):
        raise ValueError('INVALID_SEARCH_OPTION')
    rows = []
    for doc in documents:
        if file and doc['path'] != file:
            continue
        eligible, hits = search.matches(doc, queries, mode, selected)
        if eligible:
            rows.append((doc, hits, search.score(doc, queries, hits, stats, sort, selected)))
    return sorted(rows, key=lambda row: (-row[2], row[0]['id']))


def fingerprint(root, args):
    original = search.fingerprint(root, args)
    extra = {name: search.sha(root/name) for name in ('.maintenance.sqlite3', 'maintenance_view.py')}
    return hashlib.sha256(search.encoded({'parent': original, 'version': VERSION, 'extra': extra}).encode()).hexdigest()


def search_page(root, db, args, pager):
    if args.offset:
        raise ValueError('SEARCH_REQUIRES_CURSOR: use next_cursor')
    if any(not q for q in args.query):
        raise ValueError('EMPTY_QUERY_CLAUSE')
    binding = fingerprint(root, args)
    offset = search.cursor_offset(args.cursor, binding) if args.cursor else 0
    docs, stats = search.load_index(root)
    ranked = rank(docs, stats, args.query, mode=args.mode, selected=args.search_field, file=args.file, sort=args.sort)
    records = {i: {'card': json.loads(c), 'intention': json.loads(t)} for i, c, t in db.execute('SELECT id,card,intention FROM tests')}
    rows = [search.short_row(d, hits, score, records[d['id']]) for d, hits, score in ranked]
    return search.search_page(rows, binding, offset, args.limit, args.max_bytes, pager)


def lookup(root, db, identity, ref):
    if not ref.startswith('/maintenance/'):
        return search.lookup(db, identity, ref)
    facts, coverage = load(root, identity)
    if ref not in {f['ref'] for f in fields(facts)}:
        raise ValueError('INVALID_EVIDENCE_REF')
    pointer = '/'.join(ref.split('/')[:4])
    return {'id': identity, 'ref': ref, 'value': search.pointer({'maintenance': facts}, ref),
            'context_ref': pointer, 'context': search.pointer({'maintenance': facts}, pointer), 'coverage': coverage}


def view(root, identity, category='all'):
    facts, coverage = load(root, identity)
    if category not in ('all', *CATEGORIES):
        raise ValueError('UNKNOWN_MAINTENANCE_FIELD')
    rows = [{'id': identity, 'coverage': coverage}]
    for key in CATEGORIES:
        if category in ('all', key):
            rows += [{'field': key, 'fact': f} for f in facts[key]]
    return rows


def source(root, identity, ref, repository):
    facts, _ = load(root, identity)
    requested = ref.removeprefix('maintenance:')
    fact = next((f for rows in facts.values() for f in rows if f['id']==requested), None)
    if fact is None:
        raise ValueError('Source reference is not associated with this test')
    location = fact['source']
    relative = Path(location['path'])
    path = repository/relative
    if relative.is_absolute() or '..' in relative.parts or path.is_symlink() or not path.resolve().is_relative_to(repository.resolve()):
        raise ValueError('Unsafe source path')
    if search.sha(path) != location['file_sha256']:
        raise ValueError('MAINTENANCE_SOURCE_CHANGED')
    with tokenize.open(path) as stream:
        lines = stream.read().splitlines()
    return [{'path': location['path'], 'line': i+1, 'source': lines[i]}
            for i in range(location['start_line']-1, location['end_line'])]
