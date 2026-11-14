"""Read-only Stage A closeout and release verification. No model/gold access."""
import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from .generation_contract import validate
from .recovery import atomic, digest, load_plan, now, sha
from .recovery_publish import collect, reviewed
from . import maintenance_view, search_view


def require(value, message):
    if not value:raise ValueError(message)


def connect(path):
    return sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1', uri=True)


def closeout(plan_directory, execution, current, quality, output):
    require(not output.exists(), 'Refusing to overwrite closeout')
    plan=load_plan(plan_directory)
    records,states=collect(plan,current,execution)
    sample,quarantined=reviewed(quality)
    require(set(states)=={r['new_key'] for r in plan['rows']}, 'Packet inventory mismatch')
    require(all(s in {'GENERATED','FALLBACK','COST_UNKNOWN','HOLD'} for s,_ in states.values()), 'Unfinished packets')
    reused=0
    for row in plan['reuse']:
        cache=json.loads(Path(row['cache_path']).read_text())
        require(cache['status']=='GENERATED', 'Reuse contains failed cache')
        validate(cache['result'],cache['packet']);reused+=1
    with connect(execution/'ledger.sqlite3') as db:
        db.row_factory=sqlite3.Row
        requests=[dict(x) for x in db.execute('SELECT * FROM requests ORDER BY created,id')]
    require(len(requests)<=plan['request_upper_bound'], 'Request upper bound exceeded')
    require(len({(r['key'],r['attempt']) for r in requests})==len(requests), 'Duplicate attempt')
    rows={r['new_key']:r for r in plan['rows']};usage=Counter();missing=[]
    launches=defaultdict(list)
    for path in (execution/'cli').glob('*/launch.json'):
        launch=json.loads(path.read_text());launches[launch['payload_sha256']].append(path)
    for request in requests:
        require(request['key'] in rows, 'Foreign request')
        require(1<=request['attempt']<=rows[request['key']]['allowed_new_requests'], 'Attempt limit exceeded')
        require(request['state'] in {'RESPONSE_SAVED','USAGE_UNKNOWN','COST_UNKNOWN','NOT_SENT'}, 'Open request')
        launch_paths=launches[request['body_sha']]
        require(len(launch_paths)==1, 'CLI launch/request mismatch')
        launch=json.loads(launch_paths[0].read_text())
        require(launch['model']==plan['options']['model'] and launch['auth']=='chatgpt', 'Backend changed')
        path=execution/'responses'/(request['id']+'.json')
        if path.exists():
            require(sha(path)==request['response_sha'], 'Saved response hash mismatch')
            saved=json.loads(path.read_text());value=saved.get('usage') or {}
        else:
            require(request['state']=='COST_UNKNOWN', 'Missing non-unknown response');value={}
        complete=all(type(value.get(k)) is int and value[k]>=0 for k in ('input_tokens','output_tokens'))
        if complete:
            require(request['accounted']==0,'Unexpected subscription API accounting')
            usage.update({k:v for k,v in value.items() if type(v) is int})
        else:missing.append(request['id'])
    coverage=defaultdict(Counter);unresolved=[];quarantine_rows=[]
    for (base,identity),record in sorted(records.items()):
        accepted=bool(record['intention']) and record['generation_key'] not in quarantined
        coverage[base]['tests']+=1;coverage[base]['generated' if accepted else 'fallback']+=1
        coverage[base]['retained_new' if accepted and record['origin']=='new' else 'other']+=1
        if not accepted:
            code='QUALITY_QUARANTINE' if record['generation_key'] in quarantined else 'GENERATION_INCOMPLETE'
            item=dict(base_sha=base,id=identity,generation_key=record['generation_key'],reason=code,origin=record['origin'])
            unresolved.append(item)
            if code=='QUALITY_QUARANTINE':quarantine_rows.append(item)
    result=dict(version='stage-a-closeout-v1',status='PASS',at=now(),labels_read=False,new_model_calls=0,
        plan_sha256=sha(plan_directory/'plan.json'),review_sha256=sha(quality/'review.json'),
        packet_states=dict(Counter(s for s,_ in states.values())),planned_packets=len(plan['rows']),
        cli_invocations=len(requests),prior_unavailable_model_invocations=plan['prior_subscription_attempts']['count'],
        cli_start_limit_including_prior=plan['request_upper_bound']+plan['prior_subscription_attempts']['count'],
        cli_starts_are_not_provider_http_request_counts=True,reused_success_packets_validated=reused,
        known_token_usage=dict(usage),missing_usage_request_ids=missing,direct_api_calls=0,extra_credit_purchases=0,
        quality_decisions=dict(Counter(r['decision'] for r in json.loads((quality/'review.json').read_text())['records'])),
        quarantined_generation_keys=sorted(quarantined),quarantined_versioned_records=len(quarantine_rows),
        expected_generated=sum(c['generated'] for c in coverage.values()),expected_fallback=len(unresolved),
        bases={base:dict(c) for base,c in coverage.items()},sample_records=len(sample['records']))
    output.mkdir(parents=True);atomic(output/'unresolved.json',unresolved);atomic(output/'summary.json',result)
    return result


def verify_release(plan_directory,execution,current,quality,publication,output):
    require(not output.exists(),'Refusing to overwrite release verification')
    plan=load_plan(plan_directory);expected,_=collect(plan,current,execution);_,quarantined=reviewed(quality)
    source_hashes=json.loads((Path(plan['audit'])/'sources.json').read_text())['sha256']
    for name,checksum in source_hashes.items():require(sha(Path(name))==checksum,'Public source changed: '+name)
    summary=json.loads((publication/'summary.json').read_text());bases=[];field_count=0;total=Counter()
    for base in sorted({k[0] for k in expected}):
        old=current/base;root=publication/'representations'/base
        manifest=json.loads((root/'manifest.json').read_text())
        require(manifest['base_sha']==base and manifest['representation_format']=='compact-intention-v5','Release identity')
        actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='manifest.json'}
        require(not any(p.is_symlink() for p in root.rglob('*')),'Release contains symlinks')
        require(actual==set(manifest['files']),'Release file inventory')
        for name,checksum in manifest['files'].items():require(sha(root/name)==checksum,'Release hash: '+name)
        for name in ('.maintenance.sqlite3','relations.json'):
            require(sha(root/name)==sha(old/name),'Static artifact changed: '+name)
        with connect(old/'.evidence.sqlite3') as db:
            old_rows={i:(p,f,c,l) for i,p,f,c,l in db.execute('SELECT id,path,facts,context_refs,location FROM tests')}
            old_contexts=list(db.execute('SELECT * FROM contexts ORDER BY id'))
            old_edges=list(db.execute('SELECT * FROM edges ORDER BY source,target,relation,depth'))
        with connect(root/'.maintenance.sqlite3') as db:
            maintenance_facts={i:json.loads(raw) for i,raw in db.execute('SELECT id,record FROM facts')}
            members=defaultdict(lambda:defaultdict(list))
            for identity,category,ordinal,fid in db.execute('SELECT test_id,category,ordinal,fact_id FROM members ORDER BY test_id,category,ordinal'):
                members[identity][category].append(maintenance_facts[fid])
        with connect(root/'.evidence.sqlite3') as db:
            require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Evidence integrity')
            require(list(db.execute('SELECT * FROM contexts ORDER BY id'))==old_contexts,'Context evidence changed')
            require(list(db.execute('SELECT * FROM edges ORDER BY source,target,relation,depth'))==old_edges,'Relation edges changed')
            rows=list(db.execute('SELECT id,path,card,intention,facts,context_refs,location FROM tests ORDER BY id'))
            require({r[0] for r in rows}==set(old_rows),'Test identity set changed')
            cards={};counts=Counter();documents={}
            edges=defaultdict(list)
            for source,target,relation in db.execute('SELECT source,target,relation FROM edges WHERE depth=1 ORDER BY source,target,relation'):
                edges[source].append(dict(target=target,relation=relation))
            for identity,path,raw_card,raw_intention,facts,contexts,location in rows:
                require((path,facts,contexts,location)==old_rows[identity],'Static facts or source location changed')
                record=expected[(base,identity)]
                intention=record['intention'] if record['generation_key'] not in quarantined else None
                require(json.loads(raw_intention)==intention,'Published semantic provenance mismatch')
                card=json.loads(raw_card);status='GENERATED' if intention else 'STATIC_FALLBACK'
                require(card['id']==identity and card['status']==status,'Card identity/status')
                require(card['location']=={k:v for k,v in json.loads(location).items() if k!='id'},'Card location')
                if not intention:
                    require(card['goal'] is None and not card['inputs']['items'] and not card['mock']['items'] and card['scenarios']['total']==0,'Fallback retains semantic card content')
                cards[identity]=card;counts[status]+=1
                documents[identity]=dict(identity=identity,path=path,owner=identity.split('::',1)[-1].rsplit('.',1)[0] if '.' in identity.split('::',1)[-1] else '',
                    intention=intention,facts=json.loads(facts),dependencies=edges[identity],maintenance=members[identity])
        with connect(root/'.search.sqlite3') as db:
            require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Search integrity')
            indexed=list(db.execute('SELECT id,fields FROM documents'))
            require({i for i,_ in indexed}==set(old_rows),'Search misses tests')
            for identity,raw in indexed:
                fields=json.loads(raw);doc=documents[identity]
                for field in fields:
                    require(search_view.pointer(doc,field['ref'])==field['text'],'Search evidence text differs from source field')
                    if field['field'].startswith('semantic.'):
                        require(doc['intention'] is not None,'Fallback retains semantic search content')
                require({(f['field'],f['ref'],f['text']) for f in maintenance_view.fields(members[identity])} <=
                        {(f['field'],f['ref'],f['text']) for f in fields},'Existing maintenance facts missing from search')
                field_count+=len(fields)
        index=json.loads((root/'index.json').read_text());seen=[]
        require(index['format']=='compact-intention-v5','Index format')
        for entry in index['files']:
            require(entry['topic_samples']==[],'Semantic file topics enabled')
            for line in (root/entry['summaries']).read_text().splitlines():
                card=json.loads(line);require(card==cards[card['id']],'JSONL card differs from database');seen.append(card['id'])
        require(len(seen)==len(set(seen))==len(cards) and set(seen)==set(cards),'Card inventory mismatch')
        require(manifest['generated_count']==counts['GENERATED'] and manifest['fallback_count']==counts['STATIC_FALLBACK'],'Manifest counts')
        total.update(counts);bases.append(dict(base_sha=base,tests=len(cards),counts=dict(counts),status='PASS'))
        print(json.dumps(bases[-1]),flush=True)
    require(summary['generated']==total['GENERATED'] and summary['fallback']==total['STATIC_FALLBACK'],'Summary count mismatch')
    result=dict(version='stage-a-release-verification-v1',status='PASS',at=now(),bases=bases,counts=dict(total),
        source_files_rehashed=len(source_hashes),search_evidence_fields_checked=field_count,
        source_identity_static_context_relations_preserved=True,all_card_search_references_checked=True,
        labels_read=False,new_model_calls=0,quality_review_sha256=sha(quality/'review.json'),
        publication_summary_sha256=sha(publication/'summary.json'),verifier_sha256=sha(Path(__file__)))
    atomic(output,result);return result


def smoke_readers(quality,publication,output):
    """Exercise the shipped reader and public-source pagination, without gold."""
    require(not output.exists(),'Refusing to overwrite reader verification')
    rows=json.loads((quality/'sample.json').read_text())['records'];results=[];calls=0;helper_hashes=None
    for base in sorted({r['base_sha'] for r in rows}):
        root=publication/'representations'/base
        repository=Path('/data2/wangzuohit/NLPU-data/scrapy-sdd/batch/baselines')/base/'repository'
        hashes={name:sha(root/name) for name in ('maintenance_view.py','search_view.py')}
        if helper_hashes is None:helper_hashes=hashes
        require(hashes==helper_hashes,'Reader helper versions differ between bases')
        sys.path.insert(0,str(root))
        spec=importlib.util.spec_from_file_location('_stage_a_shipped_reader',root/'read.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        def call(arguments,cap=6000,ok=True):
            nonlocal calls
            buffer=io.StringIO()
            with redirect_stdout(buffer):code=module.main(arguments,root=root,repository=repository)
            raw=buffer.getvalue();value=json.loads(raw);calls+=1
            require((code==0)==ok,'Reader return status: '+str(arguments))
            require(len(raw.encode())<=cap,'Reader exceeded byte limit')
            return value
        # CLI search runs outside the project import context as it will in a
        # benchmark workspace. Source views below explicitly use the public base.
        selected=[r for r in rows if r['base_sha']==base]
        result=subprocess.run([sys.executable,'-B',str(root/'read.py'),'search','--query',selected[0]['id']],
                              capture_output=True,text=True,cwd=repository,timeout=60)
        require(result.returncode==0 and len(result.stdout.encode())<=6000,'Standalone reader failed')
        require(selected[0]['id'] in {i.get('id') for i in json.loads(result.stdout)['items']},'Search lost exact test')
        calls+=1
        for row in selected:
            identity=row['id']
            for command in ('show','scenarios','contexts','relations','neighbors'):
                call([command,identity])
            call(['detail',identity,'--field','summary','--limit','25','--max-bytes','12000'],12000)
            call(['maintenance',identity,'--field','all'])
            source=[];offset=0
            while True:
                value=call(['source',identity,'--offset',str(offset),'--limit','25'])
                source.extend(value['items']);offset=value['next_offset']
                if offset is None:break
                require(len(source)<=row['location']['end_line']-row['location']['start_line']+1,'Source pagination loop')
            lines=(repository/row['location']['path']).read_text().splitlines()
            expected=[dict(path=row['location']['path'],line=n,source=lines[n-1])
                      for n in range(row['location']['start_line'],row['location']['end_line']+1)]
            require(source==expected,'Source pagination changed or omitted lines')
            hit=call(['search','--query',identity])
            item=next(i for i in hit['items'] if i.get('id')==identity)
            match=call(['match',identity,'--ref',item['hit']['ref']])
            require(match['items'] and match['items'][0]['value']==identity,'Search identity reference failed')
        # Check deterministic cursor pagination against the actual inventory.
        file=selected[0]['location']['path']
        arguments=['search','--file',file,'--sort','id','--limit','2']
        first=call(arguments);ids=[i['id'] for i in first['items']]
        if first['next_cursor']:
            second=call([*arguments,'--cursor',first['next_cursor']]);ids.extend(i['id'] for i in second['items'])
            call([*arguments,'--query','different query','--cursor',first['next_cursor']],ok=False)
        with connect(root/'.evidence.sqlite3') as db:
            expected_ids=[i for i, in db.execute('SELECT id FROM tests WHERE path=? ORDER BY id LIMIT ?',(file,len(ids)))]
        require(ids==expected_ids and len(ids)==len(set(ids)),'Cursor duplicates, skips or changes order')
        results.append(dict(base_sha=base,sample_records=len(selected),source_line_checks=sum(
            r['location']['end_line']-r['location']['start_line']+1 for r in selected),status='PASS'))
        print(json.dumps(results[-1]),flush=True)
        sys.path.remove(str(root))
    result=dict(version='stage-a-reader-verification-v1',status='PASS',at=now(),bases=results,reader_calls=calls,
        source_samples=len(rows),source_lines=sum(x['source_line_checks'] for x in results),
        default_byte_limit=6000,expanded_byte_limit=12000,labels_read=False,new_model_calls=0,
        source_repository_explicitly_bound=True,cursor_order_and_staleness_checked=True)
    atomic(output,result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('closeout','verify','smoke'))
    for name in ('plan','execution','current','quality','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--publication',type=Path)
    args=parser.parse_args()
    common=[args.plan.resolve(),args.execution.resolve(),args.current.resolve(),args.quality.resolve()]
    if args.action=='closeout':result=closeout(*common,args.output.resolve())
    else:
        if args.publication is None:parser.error('verify requires --publication')
        result=(smoke_readers(args.quality.resolve(),args.publication.resolve(),args.output.resolve()) if args.action=='smoke'
                else verify_release(*common,args.publication.resolve(),args.output.resolve()))
    print(json.dumps({k:v for k,v in result.items() if k not in ('bases','missing_usage_request_ids')},ensure_ascii=False))


if __name__=='__main__':main()
