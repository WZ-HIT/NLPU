"""Existing-field search, faithful evidence references, and bound cursors (stdlib)."""
import base64
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

VERSION = 'existing-field-search-v1'
SORTS = ('field-bm25-v1', 'tfidf', 'id')
WEIGHTS = {'identity': 8, 'path': 5, 'owner': 5, 'facts.calls': 4,
           'facts.mock': 4, 'semantic.summary': 3, 'facts.assertions': 3,
           'facts.assignments': 2, 'dependencies': 2}
FACTS = ('assertions', 'assignments', 'calls', 'conditions', 'mock', 'parameters')
SEMANTIC = ('summary', 'inputs', 'operations', 'environment_mock', 'scenarios', 'uncertainties')
FIELDS = ('identity', 'path', 'owner', 'dependencies') + tuple('facts.'+f for f in FACTS) + tuple('semantic.'+f for f in SEMANTIC)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def tokens(text):
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    return re.findall(r'[^\W_]+', text.casefold(), re.UNICODE)


def leaves(value, pointer):
    if isinstance(value, str):
        if value:
            yield pointer, value
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from leaves(child, pointer+'/'+str(i))
    elif isinstance(value, dict):
        for key, child in value.items():
            if key in {'id', 'line', 'start_line', 'end_line', 'status', 'depth', 'evidence'}:
                continue
            yield from leaves(child, pointer+'/'+key.replace('~', '~0').replace('/', '~1'))


def project(identity, path, record, edges):
    """Project saved values only. Refs resolve in record + identity/path/owner/edges."""
    qualified = identity.split('::', 1)[-1]
    owner = qualified.rsplit('.', 1)[0] if '.' in qualified else ''
    root = dict(record, identity=identity, path=path, owner=owner, dependencies=edges)
    fields = []
    for field in FIELDS:
        if field.startswith('semantic.'):
            key = field.split('.', 1)[1]
            value, ref, origin = (record['intention'] or {}).get(key), '/intention/'+key, 'model interpretation'
        elif field.startswith('facts.'):
            key = field.split('.', 1)[1]
            value, ref, origin = record['facts'].get(key), '/facts/'+key, 'saved static fact or candidate'
        else:
            value, ref, origin = root[field], '/'+field, 'saved identity' if field != 'dependencies' else 'saved static candidate'
        for pointer, text in leaves(value, ref):
            fields.append({'field': field, 'ref': pointer, 'text': text, 'origin': origin})
    return root, fields


def read_records(db):
    edges = defaultdict(list)
    for source, target, relation in db.execute('SELECT source,target,relation FROM edges WHERE depth=1 ORDER BY source,target,relation'):
        edges[source].append({'target': target, 'relation': relation})
    for row in db.execute('SELECT id,path,card,intention,facts,context_refs,uncertainty,location FROM tests ORDER BY id'):
        identity, path = row[:2]
        record = dict(zip(('card', 'intention', 'facts', 'context_refs', 'uncertainty', 'location'), map(json.loads, row[2:])))
        root, fields = project(identity, path, record, edges[identity])
        yield {'id': identity, 'path': path, 'record': root, 'fields': fields}


def vectorize(fields):
    grouped = defaultdict(Counter)
    for field in fields:
        grouped[field['field']].update(tokens(field['text']))
    return dict(grouped)


def statistics(documents):
    df, lengths = Counter(), Counter()
    for doc in documents:
        vocabulary = set()
        for field, vector in doc['vectors'].items():
            vocabulary.update(vector)
            lengths[field] += sum(vector.values())
        df.update(vocabulary)
    n = len(documents)
    return {'n': n, 'df': dict(sorted(df.items())), 'avg': {f: lengths[f]/max(n, 1) for f in FIELDS}, 'version': VERSION}


def build_index(evidence, destination):
    with sqlite3.connect(evidence) as db:
        documents = list(read_records(db))
    for doc in documents:
        doc['vectors'] = vectorize(doc['fields'])
    stats = statistics(documents)
    with sqlite3.connect(destination) as db:
        db.execute('CREATE TABLE documents(id TEXT PRIMARY KEY,path TEXT,fields TEXT,vectors TEXT)')
        db.execute('CREATE TABLE metadata(value TEXT)')
        db.executemany('INSERT INTO documents VALUES(?,?,?,?)',
                       ((d['id'], d['path'], encoded(d['fields']), encoded(d['vectors'])) for d in documents))
        db.execute('INSERT INTO metadata VALUES(?)', (encoded(stats),))
    coverage = {}
    for field in FIELDS:
        present = sum(any(f['field'] == field for f in d['fields']) for d in documents)
        coverage[field] = {'nonempty': present, 'empty_or_missing': len(documents)-present}
    return {'tests': len(documents), 'fields': coverage,
            'status': dict(Counter(d['record']['card']['status'] for d in documents))}


def load_index(root):
    path = root/'.search.sqlite3'
    if path.is_symlink() or not path.is_file():
        raise ValueError('SEARCH_INDEX_UNSAFE')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1', uri=True) as db:
        docs = [{'id': i, 'path': p, 'fields': json.loads(f), 'vectors': json.loads(v)}
                for i, p, f, v in db.execute('SELECT id,path,fields,vectors FROM documents ORDER BY id')]
        stats = json.loads(db.execute('SELECT value FROM metadata').fetchone()[0])
    if stats['version'] != VERSION:
        raise ValueError('SEARCH_VERSION_MISMATCH')
    return docs, stats


def matches(doc, queries, mode='or', fields=()):
    values = [f for f in doc['fields'] if not fields or f['field'] in fields]
    hits = [(f, q) for f in values for q in queries if q.casefold() in f['text'].casefold()]
    eligible = not queries or (all(any(q == h[1] for h in hits) for q in queries) if mode == 'and' else bool(hits))
    return eligible, hits


def score(doc, queries, hits, stats, sort, fields=()):
    if sort == 'id' or not queries:
        return 0.0
    query_terms = set(tokens(' '.join(queries)))
    n = stats['n']
    result = 0.0
    for field, vector in doc['vectors'].items():
        if fields and field not in fields:
            continue
        weight = WEIGHTS.get(field, 1)
        length = sum(vector.values())
        if sort == 'tfidf':
            def idf(term):
                return math.log((1+n)/(1+stats['df'].get(term, 0)))+1
            norm = math.sqrt(sum(((1+math.log(tf))*idf(t))**2 for t, tf in sorted(vector.items()))) or 1
            result += weight*sum((1+math.log(vector[t]))*idf(t)**2/norm for t in sorted(query_terms) if t in vector)
        else:
            average = stats['avg'].get(field) or 1
            for term in sorted(query_terms & vector.keys()):
                frequency = stats['df'].get(term, 0)
                idf = math.log(1+(n-frequency+.5)/(frequency+.5))
                tf = vector[term]
                result += weight*idf*tf*2.2/(tf+1.2*(.25+.75*length/average))
    for field, query in hits:
        if field['text'].casefold() == query.casefold():
            term_idf = sum(math.log(1+(n-stats['df'].get(t, 0)+.5)/(stats['df'].get(t, 0)+.5)) for t in sorted(set(tokens(query))))
            result += WEIGHTS.get(field['field'], 1)*term_idf
    return result


def rank(documents, stats, queries, mode='or', fields=(), file=None, sort='field-bm25-v1'):
    if sort not in SORTS or mode not in ('and', 'or') or any(f not in FIELDS for f in fields):
        raise ValueError('INVALID_SEARCH_OPTION')
    ranked = []
    for doc in documents:
        if file and doc['path'] != file:
            continue
        eligible, hits = matches(doc, queries, mode, fields)
        if eligible:
            ranked.append((doc, hits, score(doc, queries, hits, stats, sort, fields)))
    return sorted(ranked, key=lambda row: (-row[2], row[0]['id']))


def snippet(field, query):
    raw = field['text']
    normalized, mapping = [], []
    for i, char in enumerate(raw):
        folded = char.casefold()
        normalized.append(folded)
        mapping.extend([i]*len(folded))
    offset = ''.join(normalized).find(query.casefold())
    first = mapping[offset] if offset >= 0 and mapping else 0
    last = mapping[offset+len(query.casefold())-1]+1 if offset >= 0 and query and mapping else first
    start, end = max(0, first-35), min(len(raw), max(first+100, min(last, first+140)))
    return dict(field, text=raw[start:end], start=start, end=end, query=query[:64],
                query_truncated=len(query)>64, match_start=first, match_end=last,
                truncated=start>0 or end<len(raw))


def short_row(doc, hits, relevance, record):
    summary = (record['intention'] or {}).get('summary') or ''
    hit = min(hits, key=lambda h: (-WEIGHTS.get(h[0]['field'], 1), h[0]['ref'], h[1])) if hits else None
    return {'id': doc['id'], 'status': record['card']['status'], 'goal': summary[:120],
            'goal_truncated': len(summary)>120, 'score': round(relevance, 8),
            'hit': snippet(*hit) if hit else None, 'matching_fields': len(set(h[0]['field'] for h in hits))}


def pointer(root, ref):
    if not ref.startswith('/'):
        raise ValueError('INVALID_EVIDENCE_REF')
    value = root
    try:
        for part in ref[1:].split('/'):
            part = part.replace('~1', '/').replace('~0', '~')
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError('INVALID_EVIDENCE_REF') from exc
    return value


def lookup(db, identity, ref):
    row = db.execute('SELECT path,card,intention,facts,context_refs,uncertainty,location FROM tests WHERE id=?', (identity,)).fetchone()
    if row is None:
        raise ValueError('Unknown source test ID')
    record = dict(zip(('card', 'intention', 'facts', 'context_refs', 'uncertainty', 'location'), map(json.loads, row[1:])))
    edges = [{'target': t, 'relation': r} for t, r in db.execute('SELECT target,relation FROM edges WHERE source=? AND depth=1 ORDER BY target,relation', (identity,))]
    root, fields = project(identity, row[0], record, edges)
    if ref not in {f['ref'] for f in fields}:
        raise ValueError('INVALID_EVIDENCE_REF')
    parent = ref
    if ref.startswith('/intention/scenarios/') or ref.startswith('/facts/'):
        parent = '/'.join(ref.split('/')[:4])
    return {'id': identity, 'ref': ref, 'value': pointer(root, ref),
            'context_ref': parent, 'context': pointer(root, parent), 'location': record['location']}


def fingerprint(root, args):
    payload = {'version': VERSION, 'query': args.query, 'mode': args.mode, 'fields': args.search_field,
               'file': args.file, 'sort': args.sort, 'limit': args.limit, 'max_bytes': args.max_bytes}
    payload['files'] = {name: sha(root/name) for name in ('.evidence.sqlite3', '.search.sqlite3', 'read.py', 'search_view.py')}
    return hashlib.sha256(encoded(payload).encode()).hexdigest()


def cursor(binding, offset):
    return base64.urlsafe_b64encode(encoded({'v': 1, 'b': binding, 'o': offset}).encode()).decode().rstrip('=')


def cursor_offset(value, binding):
    try:
        data = json.loads(base64.b64decode(value+'='*(-len(value)%4), altchars=b'-_', validate=True))
        if set(data) != {'v', 'b', 'o'} or data['v'] != 1 or data['b'] != binding or type(data['o']) is not int or data['o']<0:
            raise ValueError()
        return data['o']
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError('STALE_OR_INVALID_CURSOR: repeat the initial query') from exc


def search_page(rows, binding, offset, limit, max_bytes, pager):
    cap = max(4096, min(max_bytes, 12000))
    result = pager(rows, offset, limit, cap)
    if offset > result['total_units']:
        raise ValueError('STALE_OR_INVALID_CURSOR: offset outside results')
    while True:
        next_offset = offset+len(result['items'])
        result.update(next_offset=next_offset if next_offset<result['total_units'] else None,
                      next_cursor=cursor(binding, next_offset) if next_offset<result['total_units'] else None,
                      matched_test_count=len(rows), returned_unit_count=len(result['items']),
                      returned_complete_test_count=sum('id' in item for item in result['items']))
        if len(encoded(result).encode())+1 <= cap:
            return result
        if not result['items']:
            raise ValueError('OUTPUT_METADATA_EXCEEDS_BUDGET')
        result['items'].pop()


def search(root, db, args, pager):
    if args.offset:
        raise ValueError('SEARCH_REQUIRES_CURSOR: use next_cursor')
    if any(not q for q in args.query):
        raise ValueError('EMPTY_QUERY_CLAUSE: omit --query to browse all tests')
    binding = fingerprint(root, args)
    offset = cursor_offset(args.cursor, binding) if args.cursor else 0
    docs, stats = load_index(root)
    ranked = rank(docs, stats, args.query, args.mode, args.search_field, args.file, args.sort)
    cards = {i: {'card': json.loads(c), 'intention': json.loads(t)} for i, c, t in db.execute('SELECT id,card,intention FROM tests')}
    rows = [short_row(doc, hits, relevance, cards[doc['id']]) for doc, hits, relevance in ranked]
    return search_page(rows, binding, offset, args.limit, args.max_bytes, pager)
