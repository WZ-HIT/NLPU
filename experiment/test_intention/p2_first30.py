"""Authorized 90-target P2 model round; frozen controller, durable run, auto evaluation."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from . import compact_pilot as pilot, first30
from .static import write

OUTPUT = first30.DEFAULT_OUTPUT.parent/'p2-first30-v1'
REPRESENTATIONS = first30.DEFAULT_OUTPUT.parent/'p2-20261103-v1/representations'
PREVIOUS = first30.DEFAULT_OUTPUT.parent/'compact-first30-v1'
CONFIG = 'scrapy-30pr-test-intention-p2-v4.json'
LABEL = 'test-intention-p2-first30-001'
PROJECT = Path('/home/wangzuohit/NLPU')
REPORT = PROJECT/'experiment/TEST_INTENTION_P2_FIRST30_RESULTS.md'


def now():
    return datetime.now(timezone.utc).isoformat()


def runtime_check(output, target=None):
    pilot.runtime_check(output,target)
    lock=json.loads((output/'controller-lock.json').read_text())
    for name,digest in lock['files'].items():
        if first30.sha(output/'execution-root'/name)!=digest:
            raise ValueError('Frozen controller changed: '+name)


def no_positive_categories(rows):
    result=Counter({'success_correct_empty':0,'success_false_alarm':0,'run_failed':0})
    for row in rows:
        if row['status']!='NO_POSITIVE_GOLD':
            continue
        if row['state'] in {'FAILED','BLOCKED'}:
            result['run_failed']+=1
        elif row.get('false_alarm_count',0):
            result['success_false_alarm']+=1
        else:
            result['success_correct_empty']+=1
    return dict(result)


def setup(output):
    if (output/'scope.json').exists():
        raise ValueError('New setup requires a fresh output directory')
    config=json.loads((PROJECT/first30.BENCH_REL/'batch/experiments/scrapy-30pr-testcase-v1.json').read_text())
    if len(config['prs'])!=30:
        raise ValueError('Expected fixed first 30 PRs')
    authorization={'user_request':'重新运行SDD模型实验','resolved_scope':'original first 30 PR, three SDD, P2 enhanced direct Detect only',
        'target_count':90,'model':'deepseek-flash','effort':'high','rollout_limit_per_target':100000,
        'rollout_ceiling_all_targets':9000000,'timeout_seconds':2700,'formal_attempts_per_target':1,
        'historical_baseline_rerun':False,'representation_generation_requests':0,'created_utc':now(),
        'comparison_purpose':'new overall pipeline versus history; not a matched-environment representation-only estimate'}
    write(output/'authorization.json',authorization)
    pilot.setup(output,prs=config['prs'],config_name=CONFIG,experiment_id='scrapy-30pr-test-intention-p2-v4',
                single_source=False,representation_root=REPRESENTATIONS)
    scope=json.loads((output/'scope.json').read_text())
    if scope['representation_format']!='compact-intention-v4' or len(scope['targets'])!=90:
        raise ValueError('Expected 90 P2 v4 targets')
    scope['source_representation_round']='p2-20261103-v1'
    scope['comparison_purpose']=authorization['comparison_purpose']
    write(output/'scope.json',scope)
    references={'direct_history':first30.DEFAULT_OUTPUT/'host-comparison/existing-baseline-metrics.json',
                'full_evidence_history':first30.DEFAULT_OUTPUT/'host-comparison/enhanced-metrics.json',
                'compact_history':PREVIOUS/'host-comparison/metrics.json'}
    write(output/'comparison-reference-lock.json',{'files':{name:{'path':str(path),'sha256':first30.sha(path)} for name,path in references.items()},
          'purpose':'opaque report hashes only; parse for comparison after all new targets terminate'})
    # Freeze the host controller before preparing or making any model request.
    destination=output/'execution-root/experiment/test_intention'
    shutil.copytree(PROJECT/'experiment/test_intention',destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (destination.parent/'__init__.py').write_text('')
    files={p.relative_to(output/'execution-root').as_posix():first30.sha(p) for p in destination.rglob('*.py')}
    files['experiment/__init__.py']=first30.sha(destination.parent/'__init__.py')
    write(output/'controller-lock.json',{'files':files,'entrypoint':'experiment.test_intention.p2_first30',
          'source_project':str(PROJECT),'created_utc':now()})
    runtime_check(output)


def prepare(output):
    runtime_check(output)
    pilot.prepare(output,config_name=CONFIG,label=LABEL,expected_count=90)
    runtime_check(output)


def run(output):
    runtime_check(output)
    first30.run(output,expected_count=90,before_detect=lambda target:runtime_check(output,target))
    runtime_check(output)


def status(output):
    summary=json.loads((output/'execution-status.json').read_text()) if (output/'execution-status.json').exists() else {}
    summary.update(expected=90)
    if (output/'prepared-reference.json').exists():
        ref=json.loads((output/'prepared-reference.json').read_text());ledger=Path(ref['manifest']).parent/'ledger.jsonl'
        latest={}
        if ledger.exists():
            for line in ledger.read_text().splitlines():
                event=json.loads(line);latest[(event['target']['task_id'],event['target']['method'])]=event['state']
        counts=Counter(latest.values())
        summary.update(round=ref['prepared_id'],targets=dict(counts),completed=sum(counts[s] for s in ('DETECT_SEALED','FAILED','BLOCKED')),
                       pending=90-len(latest))
    return summary


def compare(output):
    runtime_check(output)
    terminal=json.loads((output/'terminal-targets.json').read_text())
    if terminal['target_count']!=90 or len(terminal['states'])!=90 or any(s not in {'DETECT_SEALED','FAILED','BLOCKED'} for s in terminal['states'].values()):
        raise ValueError('All 90 targets must terminate before evaluation')
    root,bench=first30.execution_environment(output)
    if terminal['ledger_sha256']!=first30.sha(bench/'batch/runs'/terminal['prepared_id']/'ledger.jsonl'):
        raise ValueError('Terminal ledger changed')
    scope=json.loads((output/'scope.json').read_text());ids={(t['task_id'],t['method']) for t in scope['targets']}
    frozen=json.loads((bench/'batch/runs'/terminal['prepared_id']/'prepared-round.json').read_text())
    expected={t['task_id']:t['task_manifest']['sha256'] for t in scope['targets']}
    if (len(ids)!=90 or len(frozen['targets'])!=90 or
            {(t['task_id'],t['method']) for t in frozen['targets']}!=ids or
            any(t['task_manifest']['sha256']!=expected[t['task_id']] for t in frozen['targets'])):
        raise ValueError('Public task snapshots or full scope differ')
    refs=json.loads((output/'comparison-reference-lock.json').read_text())['files']
    for reference in refs.values():
        if first30.sha(Path(reference['path']))!=reference['sha256']:
            raise ValueError('Historical reference changed')
    from batch.testcase_metrics import compute, validate, summarize
    current=compute(bench,terminal['prepared_id']);validate(current,bench)
    documents={'p2_current':current}
    for name,reference in refs.items():
        doc=json.loads(Path(reference['path']).read_text());validate(doc,bench);documents[name]=doc
    selected={name:pilot.aggregate(doc,ids,summarize) for name,doc in documents.items()}
    latest={(r['task_id'],r['method']):r for r in selected['p2_current']['rows']}
    for name,group in selected.items():
        for old in group['rows']:
            peer=latest[(old['task_id'],old['method'])]
            if (old['index_sha256'],old['labels_sha256'],old['testcase'] is None)!=(peer['index_sha256'],peer['labels_sha256'],peer['testcase'] is None):
                raise ValueError('Paired identities/labels/denominator differ')
    run_root=bench/'batch/runs'/terminal['prepared_id']
    host=output/'host-comparison';host.mkdir(mode=0o700,exist_ok=True);host.chmod(0o700)
    write(host/'metrics.json',current);write(host/'paired-targets.json',selected)
    reading=pilot.attempt_reads(run_root,scope['targets']);write(host/'reading.json',reading)
    delta=[]
    for name,group in selected.items():
        if name=='p2_current':
            continue
        for old in group['rows']:
            new=latest[(old['task_id'],old['method'])]
            difference={k:new['testcase'][k]-old['testcase'][k] for k in ('tp','fp','fn','precision','recall','f1')} if new['testcase'] is not None else None
            delta.append({'reference':name,'task_id':old['task_id'],'method':old['method'],
                          'old_status':old['status'],'new_status':new['status'],'difference':difference})
    write(host/'per-pr-differences.json',delta)
    summary={'paired_input_check':'PASS','target_count':90,'pr_count':30,'prepared_id':terminal['prepared_id'],
        'comparison_purpose':'historical overall-pipeline comparison, not representation-only causal effect',
        'methods':{name:doc['methods'] for name,doc in selected.items()},'failures':{name:doc['failed'] for name,doc in selected.items()},
        'no_positive_categories':{name:no_positive_categories(doc['rows']) for name,doc in selected.items()},
        'budget_failures':sum(r['terminal_error']=='shared rollout token budget exhausted' for r in reading),
        'limits':['30 development PR, previously used for diagnosis; no generalization claim',
                  'Historical environments differ; no new matched direct control was authorized',
                  'Tool output bytes/characters are not provider token usage; missing usage is not zero']}
    write(host/'comparison.json',summary)
    lines=['# P2增强表示：原30PR的SDD模型实验','',
        f'轮次`{terminal["prepared_id"]}`。原30PR × 三种SDD，共90项Detect，已全部终结并通过配对身份／标签检查。',
        'deepseek-flash/high，每项100,000 rollout、2700秒、一次正式尝试；没有重新生成意图、重跑历史基线或运行方案二。','',
        '下表为方法级macro指标；每种SDD的29个正例PR参加平均，失败按零分保留。无正例PR另列。','',
        '| SDD | 历史直接定位召回 | 历史精简版召回 | P2召回 | P2精度 | P2 F1 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for method in ('openspec','speckit','cc-sdd'):
        groups={name:next(m['testcase'] for m in group['methods'] if m['method']==method) for name,group in selected.items()}
        values=[groups['direct_history']['recall_macro'],groups['compact_history']['recall_macro'],
                groups['p2_current']['recall_macro'],groups['p2_current']['precision_macro'],groups['p2_current']['f1_macro']]
        lines.append('| '+method+' | '+' | '.join(f'{v*100:.2f}%' for v in values)+' |')
    lines+=['','历史运行环境没有本次P0修复，分数差异包含运行成功率、目标口径、检索与表示的共同变化，不能全部归为P2事实层。','',
            f'失败／阻塞：当前{selected["p2_current"]["failed"]}/90；历史精简版{selected["compact_history"]["failed"]}/90。',
            f'当前日志识别的rollout耗尽：{summary["budget_failures"]}项。','',
            '| 版本 | 无正例成功且空输出 | 无正例成功但误报 | 无正例运行失败 |',
            '| --- | ---: | ---: | ---: |']
    for name in ('direct_history','compact_history','p2_current'):
        values=summary['no_positive_categories'][name]
        lines.append('| '+name+' | '+' | '.join(str(values[k]) for k in ('success_correct_empty','success_false_alarm','run_failed'))+' |')
    lines+=['','完整micro指标、逐PR差值、标签和封存复核保存在宿主机`host-comparison/`。',
            '这是开发集运行结果；未读取68PR独立测试标签。实际provider用量缺失与其他成本限制须结合原始执行记录解释。']
    text='\n'.join(lines)+'\n';(host/'report.md').write_text(text);REPORT.write_text(text)
    runtime_check(output)
    write(output/'completion.json',{'status':'COMPLETE','target_count':90,'prepared_id':terminal['prepared_id'],
        'sealed_count':sum(s=='DETECT_SEALED' for s in terminal['states'].values()),
        'failed_count':selected['p2_current']['failed'],'paired_input_check':'PASS','runtime_check':'PASS',
        'report':str(REPORT),'comparison_sha256':first30.sha(host/'comparison.json'),'completed_utc':now()})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('setup','prepare','workflow','status'))
    parser.add_argument('--output',type=Path,default=OUTPUT);args=parser.parse_args()
    if args.action=='status':
        print(json.dumps(status(args.output),ensure_ascii=False));return
    steps=('run','compare') if args.action=='workflow' else (args.action,)
    for step in steps:
        write(args.output/'execution-status.json',{'stage':step,'state':'RUNNING','updated_utc':now()})
        try:
            globals()[step](args.output)
        except BaseException as exc:
            write(args.output/'execution-status.json',{'stage':step,'state':'FAILED','error':type(exc).__name__+': '+str(exc),'updated_utc':now()})
            raise
        write(args.output/'execution-status.json',{'stage':step,'state':'COMPLETED','updated_utc':now()})
        print(json.dumps({'stage':step,'state':'COMPLETED'}),flush=True)


if __name__=='__main__':
    main()
