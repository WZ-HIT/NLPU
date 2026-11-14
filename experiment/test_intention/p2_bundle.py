"""TI-09 exporter: verified pure-base source -> separate, deduplicated new facts."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import shutil
import sqlite3

from . import maintenance_static as static
from . import maintenance_view as view
from . import search_view as search
from .p1_bundle import README as P1_README
from .p2_gate import BASELINES, OUTPUT, P1

FORMAT = 'compact-intention-v4'
README = P1_README.replace('No new source facts or relationship expansion were generated in this version.',
    'New source facts supplement the preserved evidence; they are static candidates.\nNo automatic relation expansion is enabled.')+'''

## New maintenance facts (read only when relevant)

    python3 test-intentions/read.py search --query keyword --search-field maintenance.annotations
    python3 test-intentions/read.py maintenance 'TEST_ID' --field inheritance
    python3 test-intentions/read.py match 'TEST_ID' --ref '/maintenance/annotations/0/text'
    python3 test-intentions/read.py source 'TEST_ID' --ref 'maintenance:FACT_ID'

New searchable families: maintenance.annotations, maintenance.inheritance,
maintenance.context_calls, maintenance.imports, maintenance.guards. They share
weight 1. None establishes update necessity or runtime coverage. match returns
the entire fact, source span/file hash and uncertainty; target strings are static
resolution or lexical-binding candidates. Source columns are UTF-8 byte offsets.

Context calls come only from previously associated direct definitions, at most
4 per test and 16 calls per definition. Coverage records disclose skipped counts.
Dynamic bindings, full MRO, complete import resolution and resource lifetimes
are not modeled. Branch conditions have unknown polarity/truth. Empty lists
do not mean a test is irrelevant. Generated scenarios/unknowns remain preserved.
'''


def verify_parent(source):
    manifest = json.loads((source/'manifest.json').read_text())
    if manifest['representation_format'] != 'compact-intention-v3':
        raise ValueError('Expected pinned P1 v3 input')
    expected = set(manifest['files'])|{'manifest.json'}
    if any(p.is_symlink() for p in source.rglob('*')) or {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()} != expected:
        raise ValueError('Parent inventory changed')
    for name, checksum in manifest['files'].items():
        if search.sha(source/name) != checksum:
            raise ValueError('Parent source changed: '+name)
    return manifest


def build_facts(parent, repository, destination):
    for path, checksum in parent['source_files'].items():
        source = repository/path
        if source.is_symlink() or not source.resolve().is_relative_to(repository.resolve()) or search.sha(source)!=checksum:
            raise ValueError('Base source changed: '+path)
    extractor = static.Extractor(repository)
    if {p: f['sha256'] for p, f in extractor.index.files.items()} != parent['source_files']:
        raise ValueError('Source inventory differs from original pure base')
    with sqlite3.connect(destination/'.evidence.sqlite3') as db:
        ids = [i for (i,) in db.execute('SELECT id FROM tests ORDER BY id')]
        if set(ids) != set(extractor.index.tests()):
            raise ValueError('Existing-test identity inventory changed')
        associated = {i: set(json.loads(refs)) for i, refs in db.execute('SELECT id,context_refs FROM tests')}
        contexts = defaultdict(list)
        for source, target, relation in db.execute('SELECT source,target,relation FROM edges WHERE depth=1 ORDER BY source,target,relation'):
            if source in associated and target in associated[source]:
                contexts[source].append((target, relation))
    descriptions = {i: extractor.describe(i, contexts[i]) for i in ids}
    referenced = {fid for d in descriptions.values() for values in d['facts'].values() for fid in values}
    database = destination/'.maintenance.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE facts(id TEXT PRIMARY KEY,category TEXT,record TEXT)')
        db.execute('CREATE TABLE members(test_id TEXT,category TEXT,ordinal INTEGER,fact_id TEXT,PRIMARY KEY(test_id,category,ordinal))')
        db.execute('CREATE TABLE coverage(test_id TEXT PRIMARY KEY,metadata TEXT)')
        db.execute('CREATE INDEX member_fact ON members(fact_id)')
        db.executemany('INSERT INTO facts VALUES(?,?,?)',
            ((i, extractor.facts[i]['category'], search.encoded(extractor.facts[i])) for i in sorted(referenced)))
        db.executemany('INSERT INTO members VALUES(?,?,?,?)',
            ((i, category, ordinal, fid) for i, d in descriptions.items() for category, values in d['facts'].items() for ordinal, fid in enumerate(values)))
        db.executemany('INSERT INTO coverage VALUES(?,?)',
            ((i, search.encoded(d['coverage'])) for i, d in descriptions.items()))
    return descriptions, extractor


def export(source, repository, destination):
    parent = verify_parent(source)
    if destination.exists():
        raise ValueError('Refusing to overwrite P2 bundle')
    shutil.copytree(source, destination)
    (destination/'manifest.json').unlink()
    (destination/'.search.sqlite3').unlink()
    for name, target in (('reader.py','read.py'), ('search_view.py','search_view.py'), ('maintenance_view.py','maintenance_view.py')):
        shutil.copyfile(Path(__file__).with_name(name), destination/target)
    descriptions, extractor = build_facts(parent, repository, destination)
    with sqlite3.connect(destination/'.evidence.sqlite3') as db:
        docs = list(search.read_records(db))
    for doc in docs:
        facts = {c: [extractor.facts[i] for i in ids] for c, ids in descriptions[doc['id']]['facts'].items()}
        doc['fields'] += view.fields(facts)
        doc['vectors'] = search.vectorize(doc['fields'])
    stats = search.statistics(docs)
    for field in view.EXTRA_FIELDS:
        stats['avg'][field] = sum(sum(d['vectors'].get(field, {}).values()) for d in docs)/max(1,len(docs))
    stats['maintenance_version'] = static.VERSION
    with sqlite3.connect(destination/'.search.sqlite3') as db:
        db.execute('CREATE TABLE documents(id TEXT PRIMARY KEY,path TEXT,fields TEXT,vectors TEXT)')
        db.execute('CREATE TABLE metadata(value TEXT)')
        db.executemany('INSERT INTO documents VALUES(?,?,?,?)',
                       ((d['id'],d['path'],search.encoded(d['fields']),search.encoded(d['vectors'])) for d in docs))
        db.execute('INSERT INTO metadata VALUES(?)', (search.encoded(stats),))
    if search.sha(source/'.evidence.sqlite3') != search.sha(destination/'.evidence.sqlite3'):
        raise ValueError('Original evidence changed')
    coverage = {'tests': len(docs), 'status': dict(Counter(d['record']['card']['status'] for d in docs)),
                'facts': {c: sum(len(d['facts'][c]) for d in descriptions.values()) for c in static.CATEGORIES},
                'nonempty': {c: sum(bool(d['facts'][c]) for d in descriptions.values()) for c in static.CATEGORIES},
                'unique_facts': len({i for d in descriptions.values() for values in d['facts'].values() for i in values}),
                'skipped_context_definitions': sum(d['coverage']['skipped_context_definitions'] for d in descriptions.values()),
                'skipped_context_calls': sum(d['coverage']['skipped_context_calls'] for d in descriptions.values()),
                'source_errors': extractor.index.errors}
    contract = {'version': static.VERSION, 'fields': [*search.FIELDS, *view.EXTRA_FIELDS],
                'new_weights': {f:1 for f in view.EXTRA_FIELDS}, 'coverage': coverage,
                'source_columns': 'UTF-8 byte offsets', 'missing': 'unknown or empty, never proof of irrelevance',
                'not_modeled': ['dynamic dispatch/bindings', 'full MRO', 'complete import resolution', 'resource lifetimes'],
                'context_limits': {'definitions': static.MAX_CONTEXTS, 'calls_per_definition': static.MAX_CALLS}}
    (destination/'field-contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n')
    (destination/'README.md').write_text(README)
    with (destination/'.rgignore').open('a') as stream:
        stream.write('.maintenance.sqlite3\nmaintenance_view.py\n')
    manifest = dict(parent, representation_format=FORMAT, maintenance_version=static.VERSION,
                    parent_manifest_sha256=search.sha(source/'manifest.json'),
                    parent_evidence_sha256=search.sha(source/'.evidence.sqlite3'))
    manifest['files'] = {p.relative_to(destination).as_posix(): search.sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return {'base_sha': parent['base_sha'], 'coverage': coverage,
            'manifest_sha256': search.sha(destination/'manifest.json'),
            'bytes': sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    results = []
    for source in sorted((P1/'representations').iterdir()):
        if not (source/'manifest.json').is_file():
            continue
        result = export(source, BASELINES/source.name/'repository', args.output/'representations'/source.name)
        results.append(result)
        print(json.dumps({'base': source.name, 'tests': result['coverage']['tests'], 'unique_facts': result['coverage']['unique_facts']}), flush=True)
    (args.output/'bundles.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
