"""Authorized nine-target check of the compact reader, with frozen runtime bytes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys

from . import first30
from .compact import OUTPUT as COMPACT_OUTPUT
from .static import write

OUTPUT=first30.DEFAULT_OUTPUT.parent/'compact-first3-v1'
CONFIG_NAME='scrapy-3pr-test-intention-compact-v2.json'
LABEL='test-intention-compact-first3-001'
RUNTIME_REL=first30.BENCH_REL/'environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates'
RUNTIME_FILES=('config.toml','deepseek-flash.config.toml','model-catalogs/deepseek-flash/models.json')


def runtime_check(output, target=None):
    root=output/'execution-root'
    lock=json.loads((output/'runtime-lock.json').read_text())
    for path,checksum in lock['files'].items():
        actual=root/path
        if actual.is_symlink() or first30.sha(actual)!=checksum:
            raise ValueError('Frozen runtime configuration changed: '+path)
    if lock['model']!='deepseek-flash' or lock['effort']!='high' or lock['rollout_limit_tokens']!=100000:
        raise ValueError('Runtime conditions differ from the approved pilot')


def setup(output, *, prs=(8064,8067,8073), config_name=CONFIG_NAME,
          experiment_id='scrapy-3pr-test-intention-compact-v2', single_source=True,
          representation_root=None):
    if (output/'prepared-reference.json').exists():
        raise ValueError('Prepared pilot already exists; use run/status without overwriting it')
    old_scope=json.loads((first30.DEFAULT_OUTPUT/'scope.json').read_text())
    ids={f'scrapy__scrapy__pr{n}' for n in prs}
    targets=[t for t in old_scope['targets'] if t['task_id'] in ids]
    if len(targets)!=len(prs)*3 or len(ids)!=len(prs):raise ValueError('Scope must contain the authorized PRs and all three methods')
    representation_root=Path(representation_root) if representation_root is not None else COMPACT_OUTPUT/'representations'
    formats={json.loads((representation_root/t['base_sha']/'manifest.json').read_text())['representation_format'] for t in targets}
    if len(formats)!=1 or not formats <= {'compact-intention-v2','compact-intention-v3','compact-intention-v4'}:
        raise ValueError('Expected one consistent compact representation version')
    scope={**old_scope,'targets':targets,'base_shas':sorted({t['base_sha'] for t in targets}),
           'prs':list(prs),'source_representation_round':'round-bd7ad4062f5b682721540c3a',
           'authorized_target_count':len(targets),'representation_format':next(iter(formats))}
    write(output/'scope.json',scope)
    first30.mirror(output)
    root=output/'execution-root';old_root=first30.DEFAULT_OUTPUT/'execution-root'
    locked={}
    for relative in RUNTIME_FILES:
        path=RUNTIME_REL/relative
        shutil.copy2(old_root/path,root/path)
        locked[path.as_posix()]=first30.sha(root/path)
    # Verify the actual bytes, not just an asserted lock label.
    import tomllib
    total=tomllib.loads((root/RUNTIME_REL/'config.toml').read_text())['features']['rollout_budget']
    model=tomllib.loads((root/RUNTIME_REL/'deepseek-flash.config.toml').read_text())
    profile=model
    if not total['enabled'] or total['limit_tokens']!=100000 or profile['model']!='deepseek-flash' or profile['model_reasoning_effort']!='high':
        raise ValueError('Original runtime configuration is not the approved 100k/high condition')
    # Launcher is copied into this execution root; freeze its bytes too.
    launcher=first30.BENCH_REL/'batch/stages.py';locked[launcher.as_posix()]=first30.sha(root/launcher)
    for path in sorted((root / first30.BENCH_REL / 'batch/public_detect').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            locked[path.relative_to(root).as_posix()] = first30.sha(path)
    write(output/'runtime-lock.json',{'files':locked,'model':'deepseek-flash','effort':'high',
         'rollout_limit_tokens':100000,'timeout_seconds':2700,'prefill_weight':total['prefill_token_weight'],
         'sampling_weight':total['sampling_token_weight'],'historical_runtime_byte_proof':'not available for earlier runs'})
    artifacts={}
    for base in scope['base_shas']:
        source=representation_root/base
        dest=root/'experiment-artifacts/compact-intentions'/base/first30.sha(source/'manifest.json')
        if not dest.exists():shutil.copytree(source,dest)
        manifest=dest/'manifest.json'
        artifacts[base]={'path':manifest.relative_to(root).as_posix(),'sha256':first30.sha(manifest)}
    config=json.loads((root/first30.BENCH_REL/'batch/experiments/scrapy-30pr-testcase-v1.json').read_text())
    config.update(experiment_id=experiment_id,prs=scope['prs'])
    if single_source:config['sources']=config['sources'][:1]
    config['test_intention']={'entrypoint':'test-intentions/README.md','artifacts':artifacts}
    write(root/first30.BENCH_REL/'batch/experiments'/config_name,config)
    runtime_check(output)
    print(json.dumps({'stage':'SETUP','targets':len(targets),'bases':len(artifacts),'runtime_lock':'PASS'}),flush=True)


def prepare(output, *, config_name=CONFIG_NAME, label=LABEL, expected_count=9):
    root,bench=first30.execution_environment(output)
    runtime_check(output)
    from batch.rounds import prepare_round
    frozen=prepare_round(bench/'batch/experiments'/config_name,label,root=root)
    if frozen['target_count']!=expected_count:raise ValueError('Expected the authorized target count')
    write(output/'prepared-reference.json',{'prepared_id':frozen['prepared_id'],'manifest':str(bench/'batch/runs'/frozen['prepared_id']/'prepared-round.json'),'target_count':expected_count})
    runtime_check(output)
    print(json.dumps({'stage':'PREPARED','prepared_id':frozen['prepared_id'],'target_count':expected_count}),flush=True)


def run(output, *, expected_count=9):
    runtime_check(output)
    first30.run(output,expected_count=expected_count,before_detect=lambda t:runtime_check(output,t))
    runtime_check(output)


def attempt_reads(root, targets):
    rows=[]
    for target in targets:
        task=target['task_id'];method=target['method']
        directory=root/'tasks'/task/'runs'/method/'detect/executions'
        logs=list(directory.rglob('agent.jsonl'))
        info={'task_id':task,'method':method,'commands':0,'intention_commands':0,'tool_output_chars':0,'intention_output_chars':0,'reader_commands':0,'reader_output_max_bytes':0,'terminal_error':None}
        if len(logs)!=1:raise ValueError('Expected one formal attempt per target')
        for line in logs[0].read_text().splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('type')=='turn.failed':info['terminal_error']=event.get('error',{}).get('message')
            if event.get('type')!='item.completed':continue
            item=event.get('item',{})
            if item.get('type')!='command_execution':continue
            command=item.get('command','');text=item.get('aggregated_output','')
            info['commands']+=1;info['tool_output_chars']+=len(text)
            if 'test-intentions' in command:
                info['intention_commands']+=1;info['intention_output_chars']+=len(text)
            if 'test-intentions/read.py' in command:
                info['reader_commands']+=1;info['reader_output_max_bytes']=max(info['reader_output_max_bytes'],len(text.encode()))
        rows.append(info)
    return rows


def aggregate(document, ids, summarize):
    rows=[r for r in document['rows'] if (r['task_id'],r['method']) in ids]
    if len(rows)!=len(ids) or {(r['task_id'],r['method']) for r in rows}!=ids:raise ValueError('Paired report coverage differs')
    allowed={'OK','FAILED_ZERO','NO_POSITIVE_GOLD'}
    if any(r['status'] not in allowed for r in rows):raise ValueError('Invalid evaluation evidence')
    methods=[]
    for method in ('openspec','speckit','cc-sdd'):
        selected=[r for r in rows if r['method']==method]
        summary=summarize(selected,'testcase')
        scored=[r['testcase'] for r in selected if r['testcase'] is not None]
        if scored:
            tp,fp,fn=(sum(r[k] for r in scored) for k in ('tp','fp','fn'))
            independent={'precision_micro':tp/(tp+fp) if tp+fp else 0.,
                         'recall_micro':tp/(tp+fn) if tp+fn else 0.,
                         'f1_micro':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.}
            per_target=[]
            for r in scored:
                t,p,n=(r[k] for k in ('tp','fp','fn'))
                per_target.append({'precision':t/(t+p) if t+p else 0.,'recall':t/(t+n) if t+n else 0.,'f1':2*t/(2*t+p+n) if 2*t+p+n else 0.})
            independent.update({k+'_macro':sum(r[k] for r in per_target)/len(per_target) for k in ('precision','recall','f1')})
            if any(abs(summary[k]-v)>1e-12 for k,v in independent.items()):raise ValueError('Independent aggregate arithmetic differs')
        methods.append({'method':method,'statuses':dict(Counter(r['status'] for r in selected)), 'testcase':summary})
    return {'batch_id':document['batch_id'],'rows':rows,'methods':methods,
            'failed':sum(r['state'] in {'FAILED','BLOCKED'} for r in rows)}


def compare(output, *, expected_count=9, report_path=None):
    root,bench=first30.execution_environment(output)
    runtime_check(output)
    terminal=json.loads((output/'terminal-targets.json').read_text());run_root=bench/'batch/runs'/terminal['prepared_id']
    if terminal['target_count']!=expected_count or terminal['ledger_sha256']!=first30.sha(run_root/'ledger.jsonl') or any(s not in {'DETECT_SEALED','FAILED','BLOCKED'} for s in terminal['states'].values()):
        raise ValueError('Authorized-target terminal barrier is missing or stale')
    scope=json.loads((output/'scope.json').read_text());ids={(t['task_id'],t['method']) for t in scope['targets']}
    if len(ids)!=expected_count:raise ValueError('Authorized scope count differs')
    pr_count=len({t['task_id'] for t in scope['targets']})
    expected={t['task_id']:t['task_manifest']['sha256'] for t in scope['targets']}
    frozen=json.loads((run_root/'prepared-round.json').read_text())
    if {(t['task_id'],t['method']) for t in frozen['targets']}!=ids or any(t['task_manifest']['sha256']!=expected[t['task_id']] for t in frozen['targets']):raise ValueError('Public task snapshots differ')
    from batch.testcase_metrics import compute,summarize,validate
    documents={'compact':compute(bench,terminal['prepared_id'])}
    validate(documents['compact'],bench)
    # Existing, sealed host-only reports are reused after the new terminal barrier.
    for name,filename in (('baseline','existing-baseline-metrics.json'),('full_evidence','enhanced-metrics.json')):
        documents[name]=json.loads((first30.DEFAULT_OUTPUT/'host-comparison'/filename).read_text())
        validate(documents[name],bench)
    selected={name:aggregate(doc,ids,summarize) for name,doc in documents.items()}
    new={(r['task_id'],r['method']):r for r in selected['compact']['rows']}
    for name,doc in selected.items():
        for row in doc['rows']:
            peer=new[(row['task_id'],row['method'])]
            if (row['index_sha256'],row['labels_sha256'],row['testcase'] is None)!=(peer['index_sha256'],peer['labels_sha256'],peer['testcase'] is None):raise ValueError('Paired indexes, labels or denominator differ')
            m=row['testcase']
            if m is not None:
                tp,fp,fn=(m[k] for k in ('tp','fp','fn'))
                values={'precision':tp/(tp+fp) if tp+fp else 0.,'recall':tp/(tp+fn) if tp+fn else 0.,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.}
                if any(abs(m[k]-v)>1e-12 for k,v in values.items()):raise ValueError('Per-target arithmetic check failed')
    old_root=Path(json.loads((first30.DEFAULT_OUTPUT/'prepared-reference.json').read_text())['manifest']).parent
    reading={'compact':attempt_reads(run_root,scope['targets']),'full_evidence':attempt_reads(old_root,scope['targets'])}
    host=output/'host-comparison';host.mkdir(mode=0o700,exist_ok=True);host.chmod(0o700)
    write(host/'metrics.json',documents['compact']);write(host/('paired-nine.json' if expected_count==9 else 'paired-targets.json'),selected);write(host/'reading.json',reading)
    summary={'paired_input_check':'PASS','target_count':expected_count,'pr_count':pr_count,'compact_round':terminal['prepared_id'],
             'methods':{name:doc['methods'] for name,doc in selected.items()},'failures':{name:doc['failed'] for name,doc in selected.items()},
             'no_positive_false_alarms':{name:{'task_method_count':sum(r['status']=='NO_POSITIVE_GOLD' for r in doc['rows']),
                 'total':sum(r.get('false_alarm_count',0) for r in doc['rows']),
                 'by_method':{m:sum(r.get('false_alarm_count',0) for r in doc['rows'] if r['method']==m) for m in ('openspec','speckit','cc-sdd')}} for name,doc in selected.items()},
             'reading':{name:{'mean_tool_output_chars':sum(r['tool_output_chars'] for r in rows)/len(rows),'mean_intention_output_chars':sum(r['intention_output_chars'] for r in rows)/len(rows),'token_budget_failures':sum(r['terminal_error']=='shared rollout token budget exhausted' for r in rows)} for name,rows in reading.items()},
             'limits':(['Three-PR operational check, not a full-30 accuracy conclusion.'] if expected_count==9 else [])+['Output characters are not tokens; mixed tool commands may include source and formatting.','Historical runtime configuration bytes were not independently pinned.','Ignore rules and reader paging bound recommended access; native shell can bypass these conventions.']}
    per_target=[]
    for name in ('baseline','full_evidence'):
        for old in selected[name]['rows']:
            peer=new[(old['task_id'],old['method'])]
            differences={k:peer['testcase'][k]-old['testcase'][k] for k in ('tp','fp','fn','precision','recall','f1')} if peer['testcase'] is not None else None
            per_target.append({'reference':name,'task_id':old['task_id'],'method':old['method'],'old_status':old['status'],'new_status':peer['status'],'difference':differences})
    write(host/'per-pr-differences.json',per_target)
    summary['differences']={name:{m['method']:{key:next(v for v in selected['compact']['methods'] if v['method']==m['method'])['testcase'][key]-m['testcase'][key]
        for key in ('precision_macro','recall_macro','f1_macro','precision_micro','recall_micro','f1_micro')} for m in selected[name]['methods']} for name in ('baseline','full_evidence')}
    write(host/'comparison.json',summary)
    scored=selected['compact']['methods'][0]['testcase']['scored_count']
    lines=[f'# 精简意图与按需证据：首 {pr_count} 个 PR 验证','', f'沿用原首批的 {pr_count} 个PR × 三种SDD，共 {expected_count} 项。新轮次均使用锁定的 deepseek-flash/high 与 100,000 token 定位预算。','',
           f'下表为方法级macro指标，每种SDD有{scored}个有目标测试的PR参与均值；另{pr_count-scored}个无正例PR单列误报。失败项按零分保留。','',
           '| SDD | 原基线 recall | 旧证据包 recall | 精简版 recall | 精简版 precision | 精简版 F1 |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for method in ('openspec','speckit','cc-sdd'):
        m={name:next(r for r in doc['methods'] if r['method']==method)['testcase'] for name,doc in selected.items()}
        values=[m['baseline']['recall_macro'],m['full_evidence']['recall_macro'],m['compact']['recall_macro'],m['compact']['precision_macro'],m['compact']['f1_macro']]
        lines.append('| '+method+' | '+' | '.join(f'{v*100:.2f}%' for v in values)+' |')
    lines+=['',f"失败项：原基线 {selected['baseline']['failed']}/{expected_count}，旧证据包 {selected['full_evidence']['failed']}/{expected_count}，精简版 {selected['compact']['failed']}/{expected_count}。",'',
            '| 版本 | 平均全部工具输出字符 | 平均涉及意图材料的命令输出字符 | token预算失败数 |',
            '| --- | ---: | ---: | ---: |']
    for name,label in (('full_evidence','旧证据包'),('compact','精简版')):
        r=summary['reading'][name];lines.append(f"| {label} | {r['mean_tool_output_chars']:.0f} | {r['mean_intention_output_chars']:.0f} | {r['token_budget_failures']} |")
    lines+=['','这些是命令日志输出字符，不是实际计入上下文的token；混合查询也可能包含源码输出。','',
            '| 版本 | 无正例任务误报总数 | OpenSpec | Spec Kit | cc-sdd |','| --- | ---: | ---: | ---: | ---: |']
    for name,label in (('baseline','原基线'),('full_evidence','旧证据包'),('compact','精简版')):
        r=summary['no_positive_false_alarms'][name];lines.append(f"| {label} | {r['total']} | {r['by_method']['openspec']} | {r['by_method']['speckit']} | {r['by_method']['cc-sdd']} |")
    lines+=['','完整micro指标、逐PR差值及失败原因见同目录JSON；读取输出字符不等同于token。历史运行时配置字节未独立固定，运行成功率变化也可能影响指标。', '',
            '没有重跑原基线或旧证据包版本。'+('本报告仅为首3PR验证，不能推断完整30PR效果。' if expected_count==9 else '本报告保留完整首批30PR的90项目标，包括失败和无正例任务。')]
    text='\n'.join(lines)+'\n';(host/'report.md').write_text(text)
    destination=report_path or first30.SOURCE_ROOT/'experiment/TEST_INTENTION_COMPACT_RESULTS.md'
    destination.write_text(text)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('setup','prepare','run','compare','all'));parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args();steps=('setup','prepare','run','compare') if args.action=='all' else (args.action,)
    for step in steps:
        write(args.output/'execution-status.json',{'stage':step,'state':'RUNNING'})
        try:globals()[step](args.output)
        except BaseException as exc:
            write(args.output/'execution-status.json',{'stage':step,'state':'FAILED','error':type(exc).__name__+': '+str(exc)})
            raise
    write(args.output/'execution-status.json',{'stage':steps[-1],'state':'COMPLETED'})


if __name__=='__main__':main()
