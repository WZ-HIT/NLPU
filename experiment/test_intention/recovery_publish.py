"""TI-19: fixed label-free quality sampling and versioned compact publication.

No model or benchmark calls. Publishing requires a completed source review;
source facts and maintenance DB stay intact. Original bundles are read-only.
"""
from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
import shutil
import sqlite3

from .compact import make_card
from . import maintenance_view as maintenance, search_view as search
from .generation_contract import validate
from .recovery import STORE, atomic, digest, load_plan, sha

QUALITY_POLICY = dict(version='ti19-quality-policy-v1', selection='SHA256(base::id), public inputs only',
    per_base=['one reused semantic record','one new generated record, or explicit missing sample'],
    additional=['long test >=61 lines','static mock','static condition','multiple semantic scenarios',
                'saved inheritance','remaining static fallback'],
    checklist=['expected derived from assertions','conditions distinct from actions',
               'mock configuration not claimed as real execution','shared fixture not mistaken for goal',
               'multiple meaningful checks retained','unknowns not asserted as facts'],
    decisions=['ACCEPT','QUARANTINE_PACKET','NO_SEMANTICS'],
    quarantine='all tests sharing that generation key across bases, not partial model-result salvage',
    new_model_quality_calls=0)


def recovered(plan,execution):
    """Only use completed records tied to the persisted response and ledger."""
    if not (execution/'ledger.sqlite3').exists():
        return {},{}
    with sqlite3.connect((execution/'ledger.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        states={key:(state,json.loads(detail)) for key,state,detail in db.execute('SELECT key,state,detail FROM packets')}
    records={}
    for row in plan['rows']:
        state,detail=states.get(row['new_key'],('PENDING',{}))
        if state!='GENERATED':continue
        path=execution/'results'/detail['result']
        if sha(path)!=detail['result_sha256']:raise ValueError('Recovery result changed')
        record=json.loads(path.read_text())
        if record['input_sha256']!=row['new_key'] or record['packet_sha256']!=row['packet_sha256'] or record['options']!=plan['options']:
            raise ValueError('Recovery result identity changed')
        validate(record['result'],row['packet'])
        with sqlite3.connect((execution/'ledger.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
            requests=list(db.execute('SELECT id,response_sha FROM requests WHERE key=? ORDER BY attempt', (row['new_key'],)))
        if not requests:raise ValueError('Generated result without request provenance')
        response_path=execution/'responses'/(requests[-1][0]+'.json')
        if sha(response_path)!=requests[-1][1]:raise ValueError('Recovery response changed')
        response=json.loads(response_path.read_text())
        if response['status']!='completed' or json.loads(response['text'])!=record['result']:
            raise ValueError('Generated result differs from saved response')
        for origin in row['origins']:
            for base in origin['base_shas']:
                for test in record['result']['tests']:
                    key=(base,test['id'])
                    if key in records:raise ValueError('Duplicate recovered test')
                    records[key]=dict(intention=test,generation_key=row['new_key'],origin='new')
    return records,states


def collect(plan,current,execution):
    updates,states=recovered(plan,execution)
    metadata=json.loads((Path(plan['audit'])/'coverage.json').read_text())
    pinned=json.loads((Path(plan['audit'])/'sources.json').read_text())['sha256']
    original_by={(r['base_sha'],r['id']):r for r in metadata}
    all_records={}
    for base in sorted({r['base_sha'] for r in metadata}):
        root=current/base
        for name in ('manifest.json','.evidence.sqlite3'):
            path=root/name
            if sha(path)!=pinned.get(str(path.resolve())):
                raise ValueError('Parent differs from TI-13 pinned source')
        manifest=json.loads((root/'manifest.json').read_text())
        if sha(root/'.evidence.sqlite3')!=manifest['files']['.evidence.sqlite3']:
            raise ValueError('Published evidence changed')
        with sqlite3.connect((root/'.evidence.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
            for identity,raw,rawfacts,location in db.execute('SELECT id,intention,facts,location FROM tests'):
                key=(base,identity);old=original_by[key]
                semantic=json.loads(raw)
                record=updates.get(key,dict(intention=semantic,generation_key=old['cache_key'],
                                           origin='reused' if semantic else 'fallback'))
                all_records[key]=dict(record,base_sha=base,id=identity,facts=json.loads(rawfacts),
                                      location=json.loads(location))
    return all_records,states


def material_digest(records):
    return digest([{'base':base,'id':identity,'generation_key':record['generation_key'],
                    'semantic_sha256':digest(record['intention'])}
                   for (base,identity),record in sorted(records.items())])


def sample(plan_directory,current,execution,output):
    if output.exists():raise ValueError('Refusing to overwrite quality sample')
    plan=load_plan(plan_directory)
    records,states=collect(plan,current,execution)
    if len(states)!=len(plan['rows']):raise ValueError('Full recovery run not initialized')
    chosen={}
    def choose(candidates,reason,base=None):
        values=sorted(candidates,key=lambda r:digest([r['base_sha'],r['id']]))
        if values:
            row=values[0];key=(row['base_sha'],row['id'])
            chosen.setdefault(key,dict(row,reasons=[]))['reasons'].append(reason)
        else:
            missing.append(dict(base_sha=base,stratum=reason))
    missing=[]
    for base in sorted({k[0] for k in records}):
        values=[r for r in records.values() if r['base_sha']==base]
        choose([r for r in values if r['origin']=='reused'],'reused',base)
        choose([r for r in values if r['origin']=='new'],'new',base)
    values=list(records.values())
    choose([r for r in values if r['location']['end_line']-r['location']['start_line']>=60],'long')
    choose([r for r in values if r['facts'].get('mock')],'mock')
    choose([r for r in values if r['facts'].get('conditions')],'condition')
    choose([r for r in values if len((r['intention'] or {}).get('scenarios',[]))>1],'multiple_scenarios')
    inherited=[]
    for base in sorted({k[0] for k in records}):
        path=current/base/'.maintenance.sqlite3'
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            ids={identity for identity, in db.execute("SELECT DISTINCT test_id FROM members WHERE category='inheritance'")}
        inherited += [records[(base,i)] for i in ids]
    choose(inherited,'inheritance')
    choose([r for r in values if not r['intention']],'fallback')
    rows=[dict(base_sha=r['base_sha'],id=r['id'],generation_key=r['generation_key'],origin=r['origin'],
               location=r['location'],intention=r['intention'],reasons=r['reasons'],
               decision='NOT_REVIEWED',notes='',source_anchors=[]) for r in chosen.values()]
    # The locked sample and mutable review are separate artifacts.
    output.mkdir(parents=True)
    atomic(output/'sample.json',dict(policy=QUALITY_POLICY,records=rows,missing_strata=missing,
                                   plan_sha256=sha(plan_directory/'plan.json'),material_digest=material_digest(records),
                                   states_digest=digest(states),states=Counter(s[0] for s in states.values())))
    atomic(output/'review.json',dict(sample_sha256=sha(output/'sample.json'),records=rows))
    return len(rows)


def reviewed(directory):
    sample=json.loads((directory/'sample.json').read_text())
    if sample['policy']!=QUALITY_POLICY:raise ValueError('Quality policy changed')
    review=json.loads((directory/'review.json').read_text())
    if review['sample_sha256']!=sha(directory/'sample.json'):raise ValueError('Quality sample changed')
    source={(r['base_sha'],r['id']):r for r in sample['records']}
    seen=set();quarantined=set()
    for row in review['records']:
        key=(row['base_sha'],row['id'])
        if key in seen or key not in source:raise ValueError('Review sample identity mismatch')
        seen.add(key);original=source[key]
        for field in original:
            if field not in ('decision','notes','source_anchors') and row.get(field)!=original[field]:
                raise ValueError('Review altered sampled evidence')
        if row['decision'] not in QUALITY_POLICY['decisions'] or not row['notes'].strip():
            raise ValueError('Quality review incomplete')
        if row['decision']=='NO_SEMANTICS':
            if row['intention']:raise ValueError('Semantic record cannot pass as unreviewable fallback')
        elif not row['source_anchors']:
            raise ValueError('Source review needs concrete anchors')
        for anchor in row['source_anchors']:
            path=Path(anchor.get('path',''))
            if path.is_absolute() or '..' in path.parts or not path.parts or \
               not isinstance(anchor.get('start_line'),int) or not isinstance(anchor.get('end_line'),int) or \
               anchor['start_line']<1 or anchor['end_line']<anchor['start_line']:
                raise ValueError('Invalid public-source review anchor')
        if row['decision']=='QUARANTINE_PACKET':quarantined.add(row['generation_key'])
    if seen!=source.keys():raise ValueError('Quality review missing records')
    return sample,quarantined


def rebuild_search(destination):
    with sqlite3.connect(destination/'.evidence.sqlite3') as db:
        docs=list(search.read_records(db))
    with sqlite3.connect(destination/'.maintenance.sqlite3') as db:
        facts={i:json.loads(raw) for i,raw in db.execute('SELECT id,record FROM facts')}
        members=defaultdict(lambda:defaultdict(list))
        for identity,category,ordinal,fid in db.execute('SELECT test_id,category,ordinal,fact_id FROM members ORDER BY test_id,category,ordinal'):
            members[identity][category].append(facts[fid])
    for doc in docs:
        doc['fields']+=maintenance.fields(members[doc['id']])
        doc['vectors']=search.vectorize(doc['fields'])
    stats=search.statistics(docs)
    for field in maintenance.EXTRA_FIELDS:
        stats['avg'][field]=sum(sum(d['vectors'].get(field,{}).values()) for d in docs)/max(1,len(docs))
    with sqlite3.connect(destination/'.search.sqlite3') as db:
        db.executescript('CREATE TABLE documents(id TEXT PRIMARY KEY,path TEXT,fields TEXT,vectors TEXT);CREATE TABLE metadata(value TEXT);')
        db.executemany('INSERT INTO documents VALUES(?,?,?,?)',((d['id'],d['path'],search.encoded(d['fields']),search.encoded(d['vectors'])) for d in docs))
        db.execute('INSERT INTO metadata VALUES(?)',(search.encoded(stats),))


def publish(plan_directory,current,execution,quality,output,allow_partial=False):
    if output.exists():raise ValueError('Refusing to overwrite published recovery')
    plan=load_plan(plan_directory);records,states=collect(plan,current,execution)
    for name,checksum in json.loads((Path(plan['audit'])/'sources.json').read_text())['sha256'].items():
        if sha(Path(name))!=checksum:raise ValueError('TI-13 public/source input changed: '+name)
    if len(states)!=len(plan['rows']):raise ValueError('Generation run not initialized for full plan')
    pending=[key for key,(state,_) in states.items() if state in ('PENDING','NOT_SENT_BUDGET')]
    if pending and not allow_partial:raise ValueError('Pending coverage requires explicit partial publication')
    sample_document,quarantined=reviewed(quality)
    if sample_document['plan_sha256']!=sha(plan_directory/'plan.json'):raise ValueError('Quality plan differs')
    if sample_document['material_digest']!=material_digest(records) or sample_document['states_digest']!=digest(states):
        raise ValueError('Quality reviewed a different generation state')
    original=Path(plan['original']);results=[]
    output.mkdir(parents=True)
    for base in sorted({k[0] for k in records}):
        source=current/base;manifest=json.loads((source/'manifest.json').read_text())
        for name,checksum in manifest['files'].items():
            if sha(source/name)!=checksum:raise ValueError('Published parent changed')
        destination=output/'representations'/base
        shutil.copytree(source,destination)
        (destination/'manifest.json').unlink();(destination/'.search.sqlite3').unlink()
        document=json.loads((original/'static'/f'{base}.json').read_text())
        cards={};counts=Counter()
        with sqlite3.connect(destination/'.evidence.sqlite3') as db:
            for test in document['tests']:
                record=records[(base,test['id'])]
                semantic=record['intention'] if record['generation_key'] not in quarantined else None
                test=dict(test,intention=semantic,semantic_status='GENERATED' if semantic else 'STATIC_FALLBACK')
                card=make_card(test);cards[test['id']]=card;counts[test['semantic_status']]+=1
                db.execute('UPDATE tests SET card=?,intention=?,uncertainty=? WHERE id=?',
                    (search.encoded(card),search.encoded(semantic),
                     search.encoded(test['uncertainty']+((semantic or {}).get('uncertainties',[]))),test['id']))
            index=json.loads((destination/'index.json').read_text())
            index['format']='compact-intention-v5'
            for entry in index['files']:
                entry['topic_samples']=[]
                db.execute('UPDATE files SET metadata=? WHERE path=?',(search.encoded(entry),entry['path']))
                values=[cards[t['id']] for t in document['tests'] if t['path']==entry['path']]
                (destination/entry['summaries']).write_text(''.join(search.encoded(c)+'\n' for c in values))
        atomic(destination/'index.json',index)
        rebuild_search(destination)
        if sha(destination/'.maintenance.sqlite3')!=sha(source/'.maintenance.sqlite3'):
            raise ValueError('Static maintenance evidence changed')
        (destination/'README.md').write_text((source/'README.md').read_text()+
            '\nRecovery version: existing successful descriptions retain their original generation provenance; '
            'new descriptions use a separately validated evidence contract. Missing or quarantined '
            'descriptions remain STATIC_FALLBACK. File topic samples are disabled.\n')
        coverage=dict(base_sha=base,tests=sum(counts.values()),generated=counts['GENERATED'],fallback=counts['STATIC_FALLBACK'])
        contract=json.loads((destination/'field-contract.json').read_text())
        contract['semantic_coverage']=coverage;atomic(destination/'field-contract.json',contract)
        updated=dict(manifest,representation_format='compact-intention-v5',
            parent_manifest_sha256=sha(source/'manifest.json'),parent_evidence_sha256=sha(source/'.evidence.sqlite3'),
            generated_count=counts['GENERATED'],fallback_count=counts['STATIC_FALLBACK'],
            recovery_plan_sha256=sha(plan_directory/'plan.json'),quality_review_sha256=sha(quality/'review.json'),
            generation_versions=['source-evidence-intention-1',plan['options']['prompt_version']],
            file_topics='disabled, static file navigation retained')
        updated['files']={p.relative_to(destination).as_posix():sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
        atomic(destination/'manifest.json',updated);results.append(coverage)
        print(json.dumps(coverage),flush=True)
    summary=dict(version='stage-a-publication-v1',bases=results,generated=sum(r['generated'] for r in results),
                 fallback=sum(r['fallback'] for r in results),model_calls=0,quarantined_generation_keys=sorted(quarantined),
                 status='COMPLETE_COVERAGE' if not sum(r['fallback'] for r in results) else 'PARTIAL_COVERAGE',
                 quality_sample_count=len(sample_document['records']),
                 scope='22 development bases only; no Detect experiment run')
    atomic(output/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('sample','publish'))
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--execution',type=Path,required=True)
    parser.add_argument('--current',type=Path,default=STORE/'p2-20261103-v1/representations')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--quality',type=Path)
    parser.add_argument('--allow-partial',action='store_true')
    args=parser.parse_args()
    if args.action=='sample':
        print(json.dumps({'sample_records':sample(args.plan,args.current,args.execution,args.output)}))
    else:
        if args.quality is None:parser.error('publish requires --quality')
        print(json.dumps(publish(args.plan,args.current,args.execution,args.quality,args.output,args.allow_partial)))


if __name__=='__main__':main()
