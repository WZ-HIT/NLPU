"""TI-24: rebuild a strictly static B and a matched semantic C from public base facts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sqlite3

from . import reader, search_view as search, maintenance_view as maintenance
from .compact import make_card
from .stage_b_bundle import checked, write

ROOT=Path('/data2/wangzuohit/NLPU-experiments/test-intention')
OUTPUT=ROOT/'stage-c-20261109-v1'
PARENT=ROOT/'stage-b-20261109-v1/publication-v2/representations'
STATIC=ROOT/'first30-v1/static'
FORMAT='matched-intention-v1'
CODE=('read.py','legacy_read.py','search_view.py','maintenance_view.py','sensitivity_view.py')
COMMON='''# Existing tests: public base evidence

Use PR title/body and current base source to locate existing methods needing edits.
All existing tests are independently searchable; file membership and relationships
are navigation, never selection gates. Static candidates do not prove execution,
complete binding/MRO, or update necessity. Verify current source against the task.

    python3 test-intentions/read.py search --query keyword
    python3 test-intentions/read.py search --query old_api --query mock --mode and
    python3 test-intentions/read.py search --query keyword --cursor NEXT_CURSOR
    python3 test-intentions/read.py show TEST_ID
    python3 test-intentions/read.py sensitive TEST_ID
    python3 test-intentions/read.py point TEST_ID --ref /facts/calls/0
    python3 test-intentions/read.py match TEST_ID --ref /facts/calls/0/expression
    python3 test-intentions/read.py facts TEST_ID --field assertions
    python3 test-intentions/read.py maintenance TEST_ID --field imports
    python3 test-intentions/read.py source TEST_ID
    python3 test-intentions/read.py contexts TEST_ID
    python3 test-intentions/read.py relations TEST_ID

Search defaults to literal casefold OR; --mode and requires all clauses. --file
is an optional exact path. All tests are searched by default. next_cursor is bound
to the same query/options/material; other views continue with --offset next_offset.
Output defaults to 6,000 bytes/8 units, capped at 12,000 bytes/25 units. Explicitly
numbered fragments must be collected before interpretation. Total match count and
returned count differ. Score is retrieval relevance, never edit probability.

Searchable static fields: identity, path, owner, dependencies, facts.assertions,
facts.assignments, facts.calls, facts.conditions, facts.mock, facts.parameters,
maintenance.annotations, maintenance.inheritance, maintenance.context_calls,
maintenance.imports, maintenance.guards. Use these exact names with --search-field;
goal and source are not search-field names. Original source comments/docstrings
remain public. Source points disclose start-line-only or exact saved span coverage.
Associated contexts are bounded; empty fields do not establish irrelevance.

Do not dump the database, manifest, all summaries or whole graph. No production
localization stage or automatic relationship expansion is provided. Use the same
public validator and short investigation-note contract as the main Detect prompt.
'''


def guidance(group):
    if group=='B':
        return COMMON+'''
This material contains static facts only. Every test has the same STATIC_ONLY
status, without any disclosure of semantic generation success/failure. No generated
goal, scenario, model uncertainty, topic or semantic index statistics are stored.
show provides identity, location and static dependency candidates. Original static
uncertainties can be read with detail TEST_ID --field uncertainties.
'''
    return COMMON+'''
This material adds generated interpretations to the same static facts. GENERATED
and STATIC_FALLBACK disclose semantic availability; missing interpretations never
imply irrelevance. Model interpretations are not source facts or required edits.
Searchable semantic fields: semantic.summary, semantic.inputs, semantic.operations,
semantic.environment_mock, semantic.scenarios, semantic.uncertainties.

    python3 test-intentions/read.py scenarios TEST_ID
    python3 test-intentions/read.py detail TEST_ID --field summary
    python3 test-intentions/read.py detail TEST_ID --field uncertainties

Generated file topics and semantic relationships are disabled. This is partially
covered material; preserve missing semantic states rather than inferring behavior.
'''


def build_index(root):
    with reader.connect(root) as db:
        docs=list(search.read_records(db))
    # Keep precisely the same static fields and weight policy in B/C. Recompute
    # document frequencies and lengths from each group's allowed content only.
    for doc in docs:
        facts,_=maintenance.load(root,doc['id'])
        doc['fields']+=maintenance.fields(facts)
        doc['vectors']=search.vectorize(doc['fields'])
    stats=search.statistics(docs)
    for field in maintenance.EXTRA_FIELDS:
        stats['avg'][field]=sum(sum(d['vectors'].get(field,{}).values()) for d in docs)/max(1,len(docs))
    with sqlite3.connect(root/'.search.sqlite3') as db:
        db.execute('CREATE TABLE documents(id TEXT PRIMARY KEY,path TEXT,fields TEXT,vectors TEXT)')
        db.execute('CREATE TABLE metadata(value TEXT)')
        db.executemany('INSERT INTO documents VALUES(?,?,?,?)',
            ((d['id'],d['path'],search.encoded(d['fields']),search.encoded(d['vectors'])) for d in docs))
        db.execute('INSERT INTO metadata VALUES(?)',(search.encoded(stats),))
    return docs,stats


def export(source,raw_path,destination,group):
    parent=checked(source)
    raw=json.loads(raw_path.read_text());static={t['id']:t for t in raw['tests']}
    if raw['base_sha']!=parent['base_sha'] or raw['source_files']!=parent['source_files']:
        raise ValueError('Pure static provenance differs')
    if destination.exists():raise ValueError('Refusing overwrite')
    destination.mkdir(parents=True)
    for name in CODE:shutil.copyfile(source/name,destination/name)
    shutil.copyfile(source/'.maintenance.sqlite3',destination/'.maintenance.sqlite3')
    # Build a fresh database. Copy-and-UPDATE would leave semantic bytes in freed pages.
    with reader.connect(source) as original, sqlite3.connect(destination/'.evidence.sqlite3') as db:
        for sql, in original.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"):
            db.execute(sql)
        db.execute('CREATE INDEX edges_target ON edges(target)')
        ids=[];cards={};statuses=Counter()
        for identity,path,card,intention,facts,refs,uncertainty,location in original.execute('SELECT * FROM tests ORDER BY id'):
            item=static[identity];saved=json.loads(facts)
            if saved!={k:v for k,v in item['static'].items() if k!='dependency_links'}:
                raise ValueError('Original static facts differ from C')
            if group=='B':
                semantic=None;unknown=item['uncertainty']
                static_card=make_card(dict(item,semantic_status='STATIC_ONLY',intention=None))
                card_obj={k:static_card[k] for k in ('id','location','status','dependency_candidates','evidence')}
                card_obj['uncertainty_count']=len(unknown)
            else:
                semantic=json.loads(intention);unknown=json.loads(uncertainty);card_obj=json.loads(card)
            cards[identity]=card_obj;ids.append(identity);statuses[card_obj['status']]+=1
            db.execute('INSERT INTO tests VALUES(?,?,?,?,?,?,?,?)',(identity,path,search.encoded(card_obj),
                search.encoded(semantic),facts,refs,search.encoded(unknown),location))
        if set(ids)!=set(static):raise ValueError('Test inventories differ')
        for table in ('contexts','edges','files'):
            entries=original.execute('SELECT * FROM '+table).fetchall()
            if entries:
                db.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in entries[0])+')',entries)
        file_entries=[]
        for path,metadata in db.execute('SELECT path,metadata FROM files ORDER BY path').fetchall():
            entry=json.loads(metadata);entry['topic_samples']=[];file_entries.append(entry)
            file_cards=[cards[i] for i in ids if i.split('::',1)[0]==path]
            target=destination/entry['summaries'];target.parent.mkdir(exist_ok=True)
            target.write_text(''.join(search.encoded(c)+'\n' for c in file_cards))
            db.execute('UPDATE files SET metadata=? WHERE path=?',(search.encoded(entry),path))
        db.commit();db.execute('VACUUM')
    (destination/'README.md').write_text(guidance(group))
    (destination/'.rgignore').write_text('\n'.join(['manifest.json','relations.json','.evidence.sqlite3',
        '.maintenance.sqlite3','.search.sqlite3',*CODE])+'\n')
    write(destination/'index.json',{'format':FORMAT,'base_sha':parent['base_sha'],'files':file_entries})
    write(destination/'relations.json',{'format':FORMAT,'access':'read.py relations TEST_ID; neighbors TEST_ID',
        'basis':'saved static candidates only; never proof of joint update'})
    docs,stats=build_index(destination)
    fields=[*search.FIELDS,*maintenance.EXTRA_FIELDS]
    if group=='B':fields=[f for f in fields if not f.startswith('semantic.')]
    write(destination/'field-contract.json',{'version':'matched-fields-v1','fields':fields,
        'weights':search.WEIGHTS,'maintenance_weights':1,'semantic_available':group=='C',
        'missing':'unknown, never irrelevant','new_extraction':False,
        'source_points':'saved P1 start line or P2 UTF-8 column span; no runtime proof'})
    # No generation cache keys, recovery status, parent semantic hashes or coverage metadata in B.
    manifest={'schema_version':1,'representation_format':FORMAT,'material_group':group,
        'base_sha':parent['base_sha'],'source_files':parent['source_files'],'test_count':len(ids),
        'search_version':search.VERSION,'maintenance_version':parent['maintenance_version'],
        'reader_output_bytes_default':6000,'reader_output_bytes_max':12000,
        'file_topics':'disabled; static navigation only'}
    if group=='C':manifest.update(generated_count=statuses['GENERATED'],fallback_count=statuses['STATIC_FALLBACK'])
    manifest['files']={p.relative_to(destination).as_posix():search.sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    write(destination/'manifest.json',manifest)
    checked(destination)
    return {'group':group,'base_sha':parent['base_sha'],'tests':len(ids),'statuses':statuses,
            'manifest_sha256':search.sha(destination/'manifest.json'),'pure_static_sha256':search.sha(raw_path),
            'source_manifest_sha256':search.sha(source/'manifest.json'),'indexed_fields':sum(len(d['fields']) for d in docs)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args();rows=[]
    for source in sorted(PARENT.iterdir()):
        for group in ('B','C'):
            row=export(source,STATIC/(source.name+'.json'),args.output/'materials'/group/source.name,group)
            rows.append(row);print(json.dumps(row),flush=True)
    write(args.output/'materials.json',{'A':'no TI bundle mounted','bundles':rows,'new_model_calls':0})


if __name__=='__main__':main()
