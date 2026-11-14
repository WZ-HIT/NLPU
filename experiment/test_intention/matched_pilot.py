"""TI-26: 27 matched Detect targets; durable starts, no retries, terminal scoring barrier."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
import queue
import shutil
import sqlite3
import sys
import threading

from . import first30
from .matched_materials import OUTPUT,ROOT,PARENT
from .stage_b_bundle import write,checked

PROJECT=Path(__file__).resolve().parents[2]
BENCH_REL=first30.BENCH_REL
TERMINAL={'DETECT_SEALED','FAILED','BLOCKED'}
PRS=(8064,8067,8073)
METHODS=('openspec','speckit','cc-sdd')


def now():return datetime.now(timezone.utc).isoformat()


class Journal:
    def __init__(self,path):
        self.path=Path(path)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS targets(key TEXT PRIMARY KEY,state TEXT NOT NULL,starts INTEGER NOT NULL,detail TEXT NOT NULL)')

    def rows(self):
        with sqlite3.connect(self.path) as db:
            return {k:dict(state=s,starts=n,detail=json.loads(d)) for k,s,n,d in db.execute('SELECT * FROM targets')}

    def start(self,key):
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT state FROM targets WHERE key=?',(key,)).fetchone()
            if prior:raise ValueError('ALREADY_STARTED_OR_TERMINAL: '+key)
            db.execute('INSERT INTO targets VALUES(?,?,?,?)',(key,'DETECT_RUNNING',1,json.dumps({'started':now()})))

    def terminal(self,key,state,detail):
        if state not in TERMINAL:raise ValueError('Not terminal')
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT state,starts,detail FROM targets WHERE key=?',(key,)).fetchone()
            if prior and prior[0] in TERMINAL:raise ValueError('Refusing terminal rewrite')
            if not prior and state!='BLOCKED':raise ValueError('No durable start for result')
            old=json.loads(prior[2]) if prior else {}
            value=json.dumps(dict(old,**detail,ended=now()))
            if prior:db.execute('UPDATE targets SET state=?,detail=? WHERE key=?',(state,value,key))
            else:db.execute('INSERT INTO targets VALUES(?,?,?,?)',(key,state,0,value))


def key(row):return row['group']+':'+row['task_id']+':'+row['method']


def setup(output=OUTPUT):
    if (output/'execution-lock.json').exists():raise ValueError('Already set up')
    if not (output/'material-verification.json').exists():raise ValueError('Materials not accepted')
    scope=json.loads((output/'scope.json').read_text())
    if scope['prs']!=list(PRS) or len(scope['targets'])!=9:raise ValueError('Pilot scope differs')
    root=output/'execution-root';bench=root/BENCH_REL
    # Mirror was created without any model calls. Refresh only new shared launcher.
    shutil.copyfile(PROJECT/BENCH_REL/'batch/stages.py',bench/'batch/stages.py')
    runtime=BENCH_REL/'environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates'
    previous=ROOT/'p2-first30-v1/execution-root'
    for name in ('config.toml','deepseek-flash.config.toml','model-catalogs/deepseek-flash/models.json'):
        shutil.copyfile(previous/runtime/name,root/runtime/name)
    import tomllib
    total=tomllib.loads((root/runtime/'config.toml').read_text())['features']['rollout_budget']
    profile=tomllib.loads((root/runtime/'deepseek-flash.config.toml').read_text())
    if total['limit_tokens']!=100000 or not total['enabled'] or profile['model']!='deepseek-flash' or profile['model_reasoning_effort']!='high':
        raise ValueError('Runtime is not the declared 100k/high profile')
    if total['prefill_token_weight']!=1.0 or total['sampling_token_weight']!=1.0:raise ValueError('Budget weights differ')
    config=json.loads((bench/'batch/experiments/scrapy-30pr-testcase-v1.json').read_text())
    configs={}
    for group in 'ABC':
        updated=dict(config,experiment_id='ti26-matched-'+group.lower()+'-v1',prs=list(PRS),sources=config['sources'][:1])
        if group!='A':
            refs={}
            for base in scope['base_shas']:
                source=output/'materials'/group/base;checked(source)
                destination=root/'experiment-artifacts/matched'/group/base
                shutil.copytree(source,destination)
                path=destination/'manifest.json';refs[base]={'path':path.relative_to(root).as_posix(),'sha256':first30.sha(path)}
            updated['test_intention']={'entrypoint':'test-intentions/README.md','artifacts':refs}
        else:updated.pop('test_intention',None)
        path=bench/'batch/experiments'/('ti26-matched-'+group.lower()+'-v1.json');write(path,updated)
        configs[group]=path.relative_to(root).as_posix()
    schedule=json.loads((ROOT/'ti13-14-20261104-v1/design/schedule.json').read_text())
    schedule=[r for r in schedule if r['pilot']]
    if len(schedule)!=27 or {r['pr'] for r in schedule}!=set(PRS):raise ValueError('Frozen pilot schedule differs')
    write(output/'pilot-plan.json',{'version':'ti26-matched-pilot-v1','created':now(),'prs':list(PRS),
        'targets':schedule,'configs':configs,'model':'deepseek-flash','effort':'high','rollout_per_target':100000,
        'timeout_seconds':2700,'formal_attempts':1,'max_parallel':3,'no_fixed_seed_available':True,
        'dispatch':'One queue per SDD, preserve frozen group order within each PR/SDD block. Different blocks may overlap; actual start/end logged.',
        'reason':'A/B/C reuse the same per-PR/method Compose project and fixed network subnet, so they must not overlap within that block.',
        'monetary_boundary':'pending user answer; run refuses without authorization.json',
        'full_30_PR_execution_authorized':False,'pilot_scores_descriptive_only':True})
    destination=root/'experiment/test_intention'
    shutil.copytree(PROJECT/'experiment/test_intention',destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (destination.parent/'__init__.py').write_text('')
    paths=[*bench.joinpath('batch').rglob('*.py'),*bench.joinpath('schemas').glob('*.json'),
           *bench.joinpath('batch/public_detect').glob('*'),*root.joinpath(runtime).rglob('*'),
           *destination.rglob('*.py'),destination.parent/'__init__.py']
    paths=[p for p in dict.fromkeys(paths) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    write(output/'execution-lock.json',{'files':{p.relative_to(root).as_posix():first30.sha(p) for p in paths},
         'pilot_plan_sha256':first30.sha(output/'pilot-plan.json'),'configs':{g:first30.sha(root/p) for g,p in configs.items()},
         'source':'isolated execution root; no historical run mutated'})
    print('SETUP_COMPLETE: 27 targets planned, no model calls')


def check(output=OUTPUT):
    lock=json.loads((output/'execution-lock.json').read_text());root=output/'execution-root'
    if first30.sha(output/'pilot-plan.json')!=lock['pilot_plan_sha256']:raise ValueError('Pilot plan changed')
    for relative,digest in lock['files'].items():
        if first30.sha(root/relative)!=digest:raise ValueError('Frozen code/runtime changed: '+relative)
    plan=json.loads((output/'pilot-plan.json').read_text())
    for group,relative in plan['configs'].items():
        if first30.sha(root/relative)!=lock['configs'][group]:raise ValueError('Frozen config changed')
    return plan


def prepare(output=OUTPUT):
    plan=check(output);root,bench=first30.execution_environment(output)
    from batch.rounds import prepare_round
    references={}
    for group,relative in plan['configs'].items():
        frozen=prepare_round(root/relative,'ti26-matched-'+group.lower()+'-001',root=root)
        if frozen['target_count']!=9:raise ValueError('Expected 9 per group')
        references[group]={'prepared_id':frozen['prepared_id'],'manifest':str(bench/'batch/runs'/frozen['prepared_id']/'prepared-round.json'),
                           'sha256':first30.sha(bench/'batch/runs'/frozen['prepared_id']/'prepared-round.json')}
        print(json.dumps({'group':group,'stage':'PREPARED','targets':9}),flush=True)
    write(output/'prepared-groups.json',references)
    check(output)


def prepared(output=OUTPUT):
    plan=check(output);root,bench=first30.execution_environment(output)
    from batch.orchestrator import validate_prepared_manifest
    refs=json.loads((output/'prepared-groups.json').read_text());result={}
    for group,ref in refs.items():
        path=Path(ref['manifest'])
        if first30.sha(path)!=ref['sha256']:raise ValueError('Prepared reference changed')
        config,targets=validate_prepared_manifest(path,bench,root)
        if len(targets)!=9:raise ValueError('All groups must be prepared before a start')
        for target in targets:result[(group,target['task_id'],target['method'])]=(config,target)
    expected={(r['group'],r['task_id'],r['method']) for r in plan['targets']}
    if len(result)!=27 or set(result)!=expected:raise ValueError('Prepared barrier scope differs')
    return plan,refs,result


def run(output=OUTPUT):
    plan,refs,targets=prepared(output)
    authorization=json.loads((output/'authorization.json').read_text())
    if authorization.get('target_limit')!=27 or authorization.get('budget_policy')!='existing_balance_no_topup':
        raise ValueError('No supported monetary boundary; no model started')
    acceptance=json.loads((output/'offline-acceptance.json').read_text())
    if acceptance.get('status')!='PASS' or acceptance.get('execution_lock_sha256')!=first30.sha(output/'execution-lock.json'):
        raise ValueError('Offline acceptance missing or stale')
    root,bench=first30.execution_environment(output)
    from batch.orchestrator import Ledger,_run_duration_lock
    from batch.stages import detect_targets
    from batch.core import BatchError
    with (output/'controller.lock').open('a') as controller,ExitStack() as stack:
        fcntl.flock(controller,fcntl.LOCK_EX|fcntl.LOCK_NB)
        journal=Journal(output/'pilot-ledger.sqlite3');initial=journal.rows()
        if any(r['state']=='DETECT_RUNNING' for r in initial.values()):
            raise ValueError('Interrupted target: inspect external outcome; never automatically retry')
        ledgers={}
        for group,ref in refs.items():
            directory=Path(ref['manifest']).parent
            stack.enter_context(_run_duration_lock(directory,ref['prepared_id']))
            ledgers[group]=Ledger(directory/'ledger.jsonl',ref['prepared_id'],bench/'schemas/batch-ledger-event-v1.schema.json')
        events=queue.Queue();stopped=threading.Event()
        def worker(method):
            try:
                for row in plan['targets']:
                    if row['method']!=method or key(row) in initial or stopped.is_set():continue
                    config,target=targets[(row['group'],row['task_id'],row['method'])]
                    acknowledge=threading.Event();events.put(('start',row,acknowledge))
                    while not acknowledge.wait(1):
                        if stopped.is_set():return
                    if not getattr(acknowledge,'permitted',False):return
                    destination=target['task_manifest'].parent/'runs'/method/'detect/executions'/target['run_id']/'attempt-1'
                    try:
                        result=detect_targets(task_manifest=target['task_manifest'],method=method,run_id=target['run_id'],
                            output=destination,bench=bench,repository_root=root,dry_run=False,localization_protocol='testcase-v1')
                        events.put(('DETECT_SEALED',row,result))
                    except Exception as exc:
                        detail=exc.as_dict() if isinstance(exc,BatchError) else {'message':str(exc)}
                        log=destination/'agent.jsonl';text=log.read_text() if log.exists() else ''
                        refusal=any(s in text for s in ('Insufficient Balance','insufficient balance','invalid api key','Invalid API key'))
                        if refusal:stopped.set()
                        events.put(('FAILED',row,{'error':detail,'stop_new_dispatch':refusal}))
            finally:events.put(('finished',None,None))
        finished=0
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(worker,m) for m in METHODS]
            while finished<3:
                try:action,row,value=events.get(timeout=30)
                except queue.Empty:
                    print(json.dumps(status(output)),flush=True);continue
                if action=='finished':finished+=1;continue
                config,target=targets[(row['group'],row['task_id'],row['method'])]
                if action=='start':
                    if stopped.is_set():
                        detail={'error':{'code':'DISPATCH_STOPPED','message':'credential/balance boundary'},'formal_agent_started':False}
                        journal.terminal(key(row),'BLOCKED',detail)
                        ledgers[row['group']].append('detect',target,'BLOCKED',1,detail)
                        value.permitted=False;value.set();continue
                    try:
                        check(output)
                        journal.start(key(row))
                        for state in ('PLANNED','PREFLIGHT_READY','DETECT_RUNNING'):
                            ledgers[row['group']].append('detect',target,state,1,{'matched_group':row['group'],'started':now()})
                    except BaseException:stopped.set();value.set();raise
                    value.permitted=True;value.set()
                else:
                    try:
                        journal.terminal(key(row),action,{'result':value})
                        ledgers[row['group']].append('detect',target,action,1,value)
                        print(json.dumps({'key':key(row),'state':action,'at':now()}),flush=True)
                    except BaseException:stopped.set();raise
            for future in futures:future.result()
        # If the provider refuses further calls, untouched targets remain explicit blocked results.
        for row in plan['targets']:
            if key(row) in journal.rows():continue
            config,target=targets[(row['group'],row['task_id'],row['method'])]
            detail={'error':{'code':'DISPATCH_STOPPED','message':'credential/balance boundary stopped new dispatch'},'formal_agent_started':False}
            journal.terminal(key(row),'BLOCKED',detail)
            ledgers[row['group']].append('detect',target,'BLOCKED',1,detail)
        rows=journal.rows()
        if len(rows)!=27 or any(r['state'] not in TERMINAL for r in rows.values()):raise ValueError('Terminal barrier failed')
        write(output/'terminal-groups.json',{'targets':rows,'references':refs,
            'ledgers':{g:first30.sha(Path(ref['manifest']).parent/'ledger.jsonl') for g,ref in refs.items()},'at':now()})


def status(output=OUTPUT):
    path=output/'pilot-ledger.sqlite3'
    rows=Journal(path).rows() if path.exists() else {}
    return {'stage':'TI26','expected':27,'states':dict(Counter(r['state'] for r in rows.values())),
            'terminal':sum(r['state'] in TERMINAL for r in rows.values()),'formal_starts':sum(r['starts'] for r in rows.values()),
            'pending':27-len(rows)}


def compare(output=OUTPUT):
    plan,refs,targets=prepared(output);terminal=json.loads((output/'terminal-groups.json').read_text())
    if len(terminal['targets'])!=27 or any(r['state'] not in TERMINAL for r in terminal['targets'].values()):
        raise ValueError('All 27 must terminate before labels or scoring')
    for group,ref in refs.items():
        if first30.sha(Path(ref['manifest']).parent/'ledger.jsonl')!=terminal['ledgers'][group]:raise ValueError('Ledger changed')
    root,bench=first30.execution_environment(output)
    # Host-only labels are accessed by the unchanged evaluator after the barrier.
    from batch.testcase_metrics import compute,validate,summarize
    from .compact_pilot import aggregate
    documents={};identities={(r['task_id'],r['method']) for r in plan['targets']}
    for group,ref in refs.items():
        doc=compute(bench,ref['prepared_id']);validate(doc,bench)
        documents[group]=aggregate(doc,identities,summarize)
        write(output/'host-comparison'/('metrics-'+group+'.json'),doc)
    for group in 'BC':
        current={(r['task_id'],r['method']):r for r in documents[group]['rows']}
        for row in documents['A']['rows']:
            peer=current[(row['task_id'],row['method'])]
            if (row['index_sha256'],row['labels_sha256'])!=(peer['index_sha256'],peer['labels_sha256']):
                raise ValueError('Paired source identity or labels differ')
    write(output/'host-comparison/paired.json',{'paired_input_check':'PASS','groups':documents,
        'scope':'3 development PR x 3 SDD x 3 groups; descriptive pilot, not generalization',
        'no_tuning_from_scores':True})
    write(output/'pilot-completion.json',{'status':'COMPLETE','tasks':27,'states':status(output),
        'paired_input_check':'PASS','new_generation_calls':0,'new_formal_agent_starts':status(output)['formal_starts'],
        'report_source':str(output/'host-comparison/paired.json'),'at':now()})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('setup','prepare','status','run','compare','workflow'))
    parser.add_argument('--output',type=Path,default=OUTPUT);args=parser.parse_args()
    if args.action=='status':print(json.dumps(status(args.output)));return
    if args.action=='workflow':run(args.output);compare(args.output)
    else:globals()[args.action](args.output)


if __name__=='__main__':main()
