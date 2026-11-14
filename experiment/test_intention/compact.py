"""Derive small intention views from the existing base-only canonical records."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from .first30 import DEFAULT_OUTPUT
from .static import digest, write

OUTPUT = DEFAULT_OUTPUT.parent/'compact-v2'
FORMAT = 'compact-intention-v2'


def small_list(values, reference, chars=220):
    shown=[]
    for value in values:
        if len(json.dumps([*shown,value],ensure_ascii=False))>chars:
            break
        shown.append(value)
    return {'items':shown,'total':len(values),'more':len(values)-len(shown),'read':reference if len(shown)<len(values) else None}


def location(item):
    return {key:item[key] for key in ('id','path','start_line','end_line')}


def make_card(test):
    intention=test.get('intention') or {}
    identity=test['id']
    scenes=intention.get('scenarios',[])
    previews=[]
    for number,scene in enumerate(scenes):
        pair={'number':number,'conditions':scene['conditions'],'expected':scene['expected'], 'evidence':scene['evidence']}
        if len(json.dumps([*previews,pair],ensure_ascii=False))>420:
            break
        previews.append(pair)
    dependencies=[]
    for edge in test['static']['dependency_links']:
        if edge['source']==identity and edge['depth']==1:
            value={'id':edge['target'],'basis':edge['relation']+' (static candidate)'}
            if value not in dependencies:
                dependencies.append(value)
    goal=intention.get('summary')
    return {'id':identity,'location':{k:v for k,v in location(test['source']).items() if k!='id'}, 'status':test['semantic_status'],
        'goal':goal if goal and len(goal)<=350 else None,
        'goal_read':'detail '+identity+' --field summary' if goal and len(goal)>350 else None,
        'inputs':small_list(intention.get('inputs',[]),'detail '+identity+' --field inputs'),
        'mock':small_list(intention.get('environment_mock',[]),'detail '+identity+' --field environment_mock'),
        'scenarios':{'items':previews,'total':len(scenes),'more':len(scenes)-len(previews),'read':'scenarios '+identity if len(previews)<len(scenes) else None},
        'dependency_candidates':small_list(dependencies,'relations '+identity,180),
        'uncertainty_count':len(intention.get('uncertainties',[]))+len(test['uncertainty']),
        'hints_status':'NOT_SEPARATELY_GENERATED','evidence':identity}


README='''# Existing-test intentions: compact views

This index describes existing behavior, not required updates. All base tests remain
searchable. Generated descriptions are model interpretations; missing descriptions
and uncertainty do not imply irrelevance. No production-localization stage is added.

Start with small pages, using the read-only reader from the repository root:

    python3 test-intentions/read.py files
    python3 test-intentions/read.py search --query keyword
    python3 test-intentions/read.py search --query warning --query deprecat
    python3 test-intentions/read.py show 'tests/example.py::Class.test_method'

Repeated query terms are OR. Search examines all semantic fields across all tests,
including content omitted from previews. File membership is organization, not a gate.
`index.json` lists file themes and entrances only; `summaries/*.jsonl` are searchable
short cards organized by original test file. Use the reader rather than dumping files
or broad recursive searches when several matches are expected.

A card preserves input/mock hints, condition/expected pairs, static dependency
candidates, source positions, uncertainty count and evidence IDs. `more`/`read` mean
additional content exists; they never mean a missing scenario can be ignored. No
separate hints field was generated originally; do not invent it or infer PR changes.
For further evidence, request only the relevant view:

    python3 test-intentions/read.py scenarios 'TEST_ID'
    python3 test-intentions/read.py detail 'TEST_ID' --field inputs
    python3 test-intentions/read.py detail 'TEST_ID' --field operations
    python3 test-intentions/read.py detail 'TEST_ID' --field uncertainties
    python3 test-intentions/read.py facts 'TEST_ID' --field assertions
    python3 test-intentions/read.py contexts 'TEST_ID'
    python3 test-intentions/read.py relations 'TEST_ID'
    python3 test-intentions/read.py neighbors 'TEST_ID'
    python3 test-intentions/read.py source 'TEST_ID'
    python3 test-intentions/read.py source 'TEST_ID' --ref 'CONTEXT_ID'

The reader defaults to at most 6,000 UTF-8 output bytes and 8 records per request;
absolute output ceiling is 12,000 bytes. Follow `next_offset` with `--offset N` to
continue. An exceptionally large record becomes explicitly numbered JSON text
fragments; join its fragments before interpreting it. Content is not silently cut.
Read source at the returned original paths/lines when needed. The derived binary
index contains JSON intentions, static facts, deduplicated source references and
edges, NOT copied source code. Do not dump or decode the entire database, manifest
or repository graph. Full original evidence packages stay on the host for auditing.
File sizes and checksums are host integrity metadata, not relevance evidence.
'''


def export_base(source, destination):
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing compact bundle')
    destination.mkdir(parents=True)
    manifest=json.loads((source/'manifest.json').read_text())
    for name,checksum in manifest['files'].items():
        path=source/name
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:
            raise ValueError('Canonical bundle changed: '+name)
    db=sqlite3.connect(destination/'.evidence.sqlite3')
    db.executescript('''
        CREATE TABLE tests(id TEXT PRIMARY KEY,path TEXT,card TEXT,intention TEXT,facts TEXT,context_refs TEXT,uncertainty TEXT,location TEXT);
        CREATE TABLE contexts(id TEXT PRIMARY KEY,metadata TEXT);
        CREATE TABLE edges(source TEXT,target TEXT,relation TEXT,depth INTEGER,PRIMARY KEY(source,target,relation,depth));
        CREATE INDEX edges_target ON edges(target);
        CREATE TABLE files(path TEXT PRIMARY KEY,metadata TEXT);
    ''')
    groups=defaultdict(list);context_meta={};counts=defaultdict(int)
    for path in sorted((source/'tests').glob('*.json')):
        test=json.loads(path.read_text());identity=test['id'];card=make_card(test)
        refs=[]
        for context in test['contexts']:
            ref=location(context)
            ref['kind']=context['kind'];ref['source_sha256']=digest(context['source'])
            previous=context_meta.get(context['id'])
            if previous and previous!=ref:
                raise ValueError('Conflicting shared context identity: '+context['id'])
            context_meta[context['id']]=ref;refs.append(context['id']);counts['context_occurrences']+=1
        semantic=test.get('intention')
        facts={k:v for k,v in test['static'].items() if k!='dependency_links'}
        fields=[identity,test['path'],json.dumps(card,ensure_ascii=False,separators=(',',':')),
                json.dumps(semantic,ensure_ascii=False),json.dumps(facts,ensure_ascii=False),json.dumps(refs),
                json.dumps([*test['uncertainty'],*((semantic or {}).get('uncertainties',[]))],ensure_ascii=False),
                json.dumps(location(test['source']))]
        db.execute('INSERT INTO tests VALUES (?,?,?,?,?,?,?,?)',fields)
        for edge in test['static']['dependency_links']:
            db.execute('INSERT OR IGNORE INTO edges VALUES (?,?,?,?)',(edge['source'],edge['target'],edge['relation'],edge['depth']))
            counts['edge_occurrences']+=1
        groups[test['path']].append(card);counts['tests']+=1
        counts['generated']+=test['semantic_status']=='GENERATED'
    for identity,meta in sorted(context_meta.items()):
        db.execute('INSERT INTO contexts VALUES (?,?)',(identity,json.dumps(meta,ensure_ascii=False)))
    file_entries=[]
    for number,(path,cards) in enumerate(sorted(groups.items())):
        name=f'summaries/{number:04d}.jsonl'
        target=destination/name;target.parent.mkdir(exist_ok=True)
        target.write_text(''.join(json.dumps(c,ensure_ascii=False,separators=(',',':'))+'\n' for c in cards))
        themes=[]
        for card in cards:
            goal=card['goal']
            if goal and goal not in themes and sum(map(len,themes))+len(goal)<240:themes.append(goal)
        entry={'path':path,'test_count':len(cards),'topic_samples':themes,'summaries':name}
        file_entries.append(entry)
        db.execute('INSERT INTO files VALUES (?,?)',(path,json.dumps(entry,ensure_ascii=False)))
    counts['unique_contexts']=len(context_meta)
    counts['unique_edges']=db.execute('SELECT count(*) FROM edges').fetchone()[0]
    db.commit();db.execute('VACUUM');db.close()
    write(destination/'index.json',{'format':FORMAT,'base_sha':manifest['base_sha'],'files':file_entries})
    write(destination/'relations.json',{'format':FORMAT,'access':'python3 test-intentions/read.py relations TEST_ID; use neighbors TEST_ID for shared dependencies','warning':'Static candidates, not runtime proof or a selection gate. No full graph dump.'})
    (destination/'README.md').write_text(README)
    (destination/'.rgignore').write_text('manifest.json\nrelations.json\n.evidence.sqlite3\nread.py\n')
    shutil.copyfile(Path(__file__).with_name('reader.py'),destination/'read.py')
    files={p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(destination.rglob('*')) if p.is_file()}
    result={'schema_version':1,'representation_format':FORMAT,'base_sha':manifest['base_sha'],
            'source_files':manifest['source_files'],'source_bundle_sha256':hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),
            'test_count':counts['tests'],'generated_count':counts['generated'],
            'fallback_count':counts['tests']-counts['generated'],'files':files,
            'reader_output_bytes_default':6000,'reader_output_bytes_max':12000}
    write(destination/'manifest.json',result)
    counts['old_bytes']=sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
    counts['new_bytes']=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())
    counts['old_index_bytes']=(source/'index.json').stat().st_size
    counts['new_index_bytes']=(destination/'index.json').stat().st_size
    counts['new_default_text_bytes']=sum(p.stat().st_size for p in destination.glob('summaries/*'))+(destination/'index.json').stat().st_size
    return {'base':manifest['base_sha'],**counts}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args();out=args.output
    scope=json.loads((DEFAULT_OUTPUT/'scope.json').read_text());stats=[]
    for base in scope['base_shas']:
        stats.append(export_base(DEFAULT_OUTPUT/'representations'/base,out/'representations'/base))
        print(json.dumps(stats[-1]),flush=True)
    write(out/'export-summary.json',{'format':FORMAT,'new_model_requests':0,'bases':stats,
        'old_bytes':sum(r['old_bytes'] for r in stats),'new_bytes':sum(r['new_bytes'] for r in stats)})


if __name__=='__main__':main()
