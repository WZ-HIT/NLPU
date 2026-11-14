"""Authorized D-only 30-PR run, pinned to C runtime and frozen D material.

No generation or retries. Historical C is never silently presented as a fresh control.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

from . import first30, matched_completion as full, matched_pilot
from .stage_b_bundle import checked

PREVIOUS = Path('/data2/wangzuohit/NLPU-experiments/test-intention/stage-c-bc-20261110-v1')
PUBLICATION = PREVIOUS.parent/'dynamic-d-20261113-v1'
OUTPUT = PREVIOUS.parent/'dynamic-d-experiment-20261114-v1'
TOTAL = 90


def configure(output):
    full.OUTPUT = output
    full.GROUPS = ('D',)
    full.TOTAL = full.NEW = TOTAL
    full.REUSED = 0


def progress(output, stage, **kwargs):
    value = {'at': full.now(), 'group': 'D', 'stage': stage, **kwargs}
    full.write(output/'execution-status.json', value)
    print(json.dumps(value, ensure_ascii=False), flush=True)


def setup(output):
    if output.exists():
        raise ValueError('Use a new experiment directory; do not overwrite or restart unknown formal targets')
    output.mkdir(parents=True)
    progress(output, 'COPYING_FROZEN_C_RUNTIME_NO_MODELS')
    material = full.read(PUBLICATION/'materials.json')
    acceptance = full.read(PUBLICATION/'offline-acceptance.json')
    if acceptance['status'] != 'PASS' or material['prs'] != 30 or len(material['bases']) != 22:
        raise ValueError('Frozen D publication not accepted')
    oldroot = PREVIOUS/'execution-root'; root = output/'execution-root'
    def ignore(directory, names):
        relative = Path(directory).relative_to(oldroot).as_posix()
        skip = {'__pycache__', '.pytest_cache'} & set(names)
        if relative == 'sdd-bench/scrapy-sdd/batch':
            skip |= {'runs'} & set(names)
        if relative == 'experiment-artifacts':
            skip |= set(names)
        return skip
    shutil.copytree(oldroot, root, ignore=ignore)
    bench = root/first30.BENCH_REL
    # Runtime/launcher stay C bytes; these reviewed files add D entrypoints only.
    project = Path(__file__).resolve().parents[2]
    overlays = [first30.BENCH_REL/'batch/stages.py', first30.BENCH_REL/'batch/scaffold.py',
                first30.BENCH_REL/'batch/dynamic_trace.py']
    overlays += [Path('experiment/test_intention')/n for n in (
        'dynamic_experiment.py', 'dynamic_runtime_probe.py', 'matched_completion.py',
        'matched_completion_acceptance.py', 'first30.py', 'matched_pilot.py')]
    for relative in overlays:
        target = root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(project/relative,target)
    # Acceptance probe is mounted standalone at the existing, audited container entrance.
    shutil.copyfile(project/'experiment/test_intention/dynamic_runtime_probe.py',
                    root/'experiment/test_intention/matched_runtime_probe.py')
    config = full.read(bench/'batch/experiments/scrapy-30pr-testcase-v1.json')
    oldplan = full.read(PREVIOUS/'plan.json')
    schedule = [dict(r,group='D',pilot=False) for r in oldplan['targets'] if r['group']=='C']
    if len(schedule)!=TOTAL or len({(r['task_id'],r['method']) for r in schedule})!=TOTAL:
        raise ValueError('D scope must be the same 90 C task/method identities')
    artifacts={};source_hashes={};publication_bases={b['base_sha']:b for b in material['bases']}
    for base in sorted({r['base_sha'] for r in schedule}):
        source=PUBLICATION/'materials/D'/base
        if first30.sha(source/'manifest.json')!=publication_bases[base]['manifest_sha256']:
            raise ValueError('D publication manifest changed')
        checked(source)
        destination=root/'experiment-artifacts/dynamic/D'/base
        shutil.copytree(source,destination)
        artifacts[base]={'path':(destination/'manifest.json').relative_to(root).as_posix(),
                         'sha256':first30.sha(destination/'manifest.json')}
        source_hashes[str(source/'manifest.json')]=first30.sha(source/'manifest.json')
        progress(output,'COPYING_D_MATERIAL_NO_MODELS',bases=len(artifacts),expected_bases=22)
    config.update(experiment_id='dynamic-d-first30-20261114-v1',
                  test_intention={'entrypoint':'test-intentions/README.md','artifacts':artifacts})
    config.pop('dynamic_trace',None)
    config_path=bench/'batch/experiments/dynamic-d-first30-20261114-v1.json'
    full.write(config_path,config)
    runtime=bench/'environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates'
    common=tomllib.loads((runtime/'config.toml').read_text())
    profile=tomllib.loads((runtime/'deepseek-flash.config.toml').read_text())
    if (common['features']['rollout_budget']['limit_tokens']!=100000 or
            not common['features']['rollout_budget']['enabled'] or
            profile['model']!='deepseek-flash' or profile['model_reasoning_effort']!='high'):
        raise ValueError('Runtime differs from C bounds')
    files={};oldlock=full.read(PREVIOUS/'execution-lock.json')['files']
    allowed={str(p) for p in overlays}|{'experiment/test_intention/matched_runtime_probe.py'}
    for relative,digest in oldlock.items():
        if '/batch/runs/' in relative:continue
        path=root/relative
        if not path.is_file():raise ValueError('Frozen C dependency missing: '+relative)
        actual=first30.sha(path)
        if relative not in allowed and actual!=digest:
            raise ValueError('Unexpected C runtime/source drift: '+relative)
        files[relative]=actual
    for relative in allowed:files[relative]=first30.sha(root/relative)
    files[config_path.relative_to(root).as_posix()]=first30.sha(config_path)
    plan={'version':'dynamic-d-run-v1','created_at':full.now(),'groups':['D'],'prs':config['prs'],
          'targets':schedule,'configs':{'D':config_path.relative_to(root).as_posix()},
          'new_target_count':90,'total_target_count':90,'reused_target_count':0,
          'model':'deepseek-flash','effort':'high','rollout_per_target':100000,
          'timeout_seconds':2700,'formal_attempts':1,'max_parallel':3,
          'budget_policy':'existing_balance_no_topup','topup_allowed':False,
          'historical_C_reference':str(PREVIOUS/'host-comparison/paired.json'),
          'comparison_limit':'C is historical. No new C run authorized in this D-only start; no isolated causal claim.',
          'scope_source':str(PREVIOUS/'plan.json'),'scope_source_sha256':first30.sha(PREVIOUS/'plan.json'),
          'publication_source_files':source_hashes}
    full.write(output/'plan.json',plan)
    full.write(output/'reused-rows.json',{'source':str(PREVIOUS/'plan.json'),
               'source_sha256':first30.sha(PREVIOUS/'plan.json'),'groups':{'D':[]}})
    full.write(output/'authorization.json',{'status':'AUTHORIZED_BY_USER','user_request':'请开始D组实验',
               'groups':['D'],'target_limit':90,'budget_policy':'existing_balance_no_topup',
               'retries_allowed':False,'topup_allowed':False,'new_generation_requests':0,
               'inherited_budget_policy_source':str(PREVIOUS/'authorization.json'),
               'plan_sha256':first30.sha(output/'plan.json')})
    full.write(output/'execution-lock.json',{'files':files,'plan_sha256':first30.sha(output/'plan.json'),
               'pilot_reuse_sha256':first30.sha(output/'reused-rows.json')})
    progress(output,'SETUP_COMPLETE_NO_MODELS',targets=TOTAL)


def prepare(output):
    plan=full.check(output);root,bench=first30.execution_environment(output)
    from batch.rounds import prepare_round
    manifest=prepare_round(root/plan['configs']['D'],'dynamic-d-first30-20261114-001',root=root)
    if manifest['target_count']!=90:raise ValueError('Expected exactly 90 D targets')
    path=bench/'batch/runs'/manifest['prepared_id']/'prepared-round.json'
    refs={'D':{'prepared_id':manifest['prepared_id'],'manifest':str(path),'sha256':first30.sha(path)}}
    full.write(output/'prepared-groups.json',refs)
    lock=full.read(output/'execution-lock.json')
    lock['files'][path.relative_to(root).as_posix()]=first30.sha(path)
    full.write(output/'execution-lock.json',lock)
    progress(output,'PREPARED_NO_MODELS',targets=90,prepared_id=manifest['prepared_id'])


def historical_inputs():
    result={}
    for parent in [PREVIOUS,full.PILOT]:
        ref=full.read(parent/'prepared-groups.json')['C']
        if first30.sha(Path(ref['manifest']))!=ref['sha256']:raise ValueError('Historical C manifest changed')
        root=parent/'execution-root'
        for target in full.read(Path(ref['manifest']))['targets']:
            reference=target['task_manifest'];path=root/reference['path']
            result[(target['task_id'],target['method'])]=path.parent
    return result


def acceptance(output):
    plan,refs,targets=full.prepared(output);root,bench=first30.execution_environment(output)
    from .matched_completion_acceptance import workspace_files,probe
    from batch.stages import detect_prompt,matched_material_prompt
    old=historical_inputs();rows=[];selected={}
    for row in plan['targets']:
        _,target=targets[('D',row['task_id'],row['method'])]
        task=target['task_manifest'].parent;workspace=task/'runs'/row['method']/'detect/workspace'
        bundle=checked(workspace/'test-intentions')
        if bundle['material_group']!='D' or (workspace/'test-traces').exists():raise ValueError('Wrong D input')
        original=old[(row['task_id'],row['method'])]
        if first30.sha(task/'experiment-inputs/task.md')!=first30.sha(original/'experiment-inputs/task.md'):
            raise ValueError('Task differs from C')
        if workspace_files(workspace)!=workspace_files(original/'runs'/row['method']/'detect/workspace'):
            raise ValueError('Initial source/SDD differs from C')
        for relative,digest in bundle['source_files'].items():
            if first30.sha(workspace/relative)!=digest:raise ValueError('D source differs from base')
        expected=plan['publication_source_files'][str(PUBLICATION/'materials/D'/row['base_sha']/'manifest.json')]
        if first30.sha(workspace/'test-intentions/manifest.json')!=expected:raise ValueError('D mount changed')
        rows.append({'task_id':row['task_id'],'method':row['method'],'base_sha':row['base_sha'],
                     'material_sha256':expected,'status':'PASS'})
        selected.setdefault((row['base_sha'],row['method']),(row,target))
    full.write(output/'prepared-input-verification.json',{'status':'PASS','targets':rows,'count':len(rows),
               'historical_C_source_and_task_match':True,'comparison_is_not_contemporaneous_C':True})
    progress(output,'CONTAINER_PROBES_NO_MODELS',combinations=len(selected))
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(probe,output,row,target) for row,target in selected.values()]
        probes=[f.result() for f in futures]
    if any(p['returncode'] or not p['probe'].get('pass') for p in probes):raise ValueError('Container D probe failed')
    for method in full.METHODS:
        (output/('prompt-'+method+'.txt')).write_text(detect_prompt(method,'testcase-v1')+matched_material_prompt('D'))
    key=Path.home()/'.config/sdd-bench/deepseek-api-key'
    if not key.is_file() or key.is_symlink() or not key.stat().st_size:raise ValueError('Credential file unavailable')
    full.write(output/'offline-acceptance.json',{'status':'PASS','targets':90,'container_combinations':len(probes),
               'execution_lock_sha256':first30.sha(output/'execution-lock.json'),
               'provider_requests':0,'credential_mounted_in_probes':False,
               'prepared_input_verification_sha256':first30.sha(output/'prepared-input-verification.json')})
    progress(output,'ACCEPTED_READY_FOR_AUTHORIZED_D_RUN',targets=90)


def compare(output):
    terminal=full.read(output/'terminal.json')
    if len(terminal['targets'])!=90 or any(r['state'] not in matched_pilot.TERMINAL for r in terminal['targets'].values()):
        raise ValueError('All 90 terminal outcomes required before labels')
    plan,refs,targets=full.prepared(output);root,bench=first30.execution_environment(output)
    from batch.testcase_metrics import compute,validate,summarize
    ref=refs['D']
    if first30.sha(Path(ref['manifest']).parent/'ledger.jsonl')!=terminal['ledgers']['D']:
        raise ValueError('Ledger changed after terminal barrier')
    document=compute(bench,ref['prepared_id']);validate(document,bench);full.verify_set_counts(document)
    rows=document['rows'];counts=full.all_task_counts(rows)
    result={'group':'D','targets':90,'at':full.now(),'all_task_counts':counts,
            'methods':{m:summarize([r for r in rows if r['method']==m],'testcase') for m in full.METHODS},
            'rows':rows,'historical_C_reference':plan['historical_C_reference'],
            'comparison_limit':plan['comparison_limit']}
    full.write(output/'host-comparison/metrics-D.json',document)
    full.write(output/'host-comparison/results-D.json',result)
    audits=[dict(full.log_audit(root,target),group='D') for _,target in targets.values()]
    full.write(output/'runtime-audit.json',{'rows':audits,'at':full.now()})
    full.write(output/'token-usage-summary.json',full.usage_summary(audits))
    macro={k:sum(result['methods'][m][k+'_macro'] for m in full.METHODS)/3 for k in ['precision','recall','f1']}
    result['macro']=macro
    full.write(output/'host-comparison/results-D.json',result)
    (output/'RESULTS.md').write_text('# D 组实验结果\n\n'+
        '范围：30 PR × 3 SDD，90 项；失败保留，无正例任务单列。C 是历史对照，不是同期重跑。\n\n'+
        f"Macro P/R/F1：{macro['precision']:.2%} / {macro['recall']:.2%} / {macro['f1']:.2%}。\n\n"+
        f"全部计数：{json.dumps(counts,ensure_ascii=False)}\n\n完整结果见 host-comparison/results-D.json。\n")
    full.write(output/'completion.json',{'status':'COMPLETE','group':'D','targets':90,'at':full.now(),
               'states':full.status(output),'results_sha256':first30.sha(output/'host-comparison/results-D.json')})
    progress(output,'COMPLETE',**full.status(output))


def workflow(output):
    with (output/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            if not (output/'prepared-groups.json').exists():
                progress(output,'PREPARING_NO_MODELS');prepare(output)
            if not (output/'offline-acceptance.json').exists():acceptance(output)
            progress(output,'RUNNING_AUTHORIZED_D_ONLY',**full.status(output))
            full.run(output)
            progress(output,'ALL_TERMINAL_SCORING_ON_HOST',**full.status(output));compare(output)
        except BaseException as exc:
            progress(output,'STOPPED_INSPECT_REQUIRED',error_type=type(exc).__name__,error=str(exc),
                     automatic_model_retries=0,**full.status(output))
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['setup','prepare','acceptance','run','compare','workflow','status'])
    parser.add_argument('--output',type=Path,default=OUTPUT);args=parser.parse_args()
    output=args.output.resolve();configure(output)
    {'setup':setup,'prepare':prepare,'acceptance':acceptance,'run':full.run,
     'compare':compare,'workflow':workflow,'status':lambda o:print(json.dumps(full.status(o)))}[args.action](output)


if __name__=='__main__':main()
