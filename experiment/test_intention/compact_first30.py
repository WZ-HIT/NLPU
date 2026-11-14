"""Fresh authorized first-30 compact round; all historical targets stay unchanged."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from . import compact_pilot as pilot
from . import first30
from .static import write

OUTPUT=first30.DEFAULT_OUTPUT.parent/'compact-first30-v1'
CONFIG_NAME='scrapy-30pr-test-intention-compact-v2.json'
LABEL='test-intention-compact-first30-001'
REPORT=first30.SOURCE_ROOT/'experiment/TEST_INTENTION_COMPACT_FIRST30_RESULTS.md'


def status(output=OUTPUT):
    """Read-only progress, without predictions or host evaluation inputs."""
    result=json.loads((output/'execution-status.json').read_text())
    reference=output/'prepared-reference.json'
    if reference.exists():
        ref=json.loads(reference.read_text());result['round']=ref['prepared_id']
        events=(Path(ref['manifest']).parent/'ledger.jsonl').read_text().splitlines()
        latest={}
        for line in events:
            event=json.loads(line);target=event['target']
            latest[(target['task_id'],target['method'])]=event['state']
        result['targets']=dict(Counter(latest.values()))
        result['completed']=sum(v in {'DETECT_SEALED','FAILED','BLOCKED'} for v in latest.values())
        result['expected']=90
    return result


def setup(output):
    config=json.loads((first30.SOURCE_ROOT/first30.BENCH_REL/'batch/experiments/scrapy-30pr-testcase-v1.json').read_text())
    if len(config['prs'])!=30:raise ValueError('Expected the original ordered first 30 PRs')
    pilot.setup(output,prs=config['prs'],config_name=CONFIG_NAME,
                experiment_id='scrapy-30pr-test-intention-compact-v2',single_source=False)
    reference=json.loads((pilot.OUTPUT/'runtime-lock.json').read_text())
    current=json.loads((output/'runtime-lock.json').read_text())
    if current['files']!=reference['files']:
        raise ValueError('Full run runtime bytes differ from the successful compact pilot')
    # The two pilot bases must use byte-identical compact bundles, and all 22
    # full-round bases must derive from the existing verified compact export.
    old_ref=json.loads((pilot.OUTPUT/'prepared-reference.json').read_text())
    old_frozen=json.loads(Path(old_ref['manifest']).read_text())
    old_config_ref=old_frozen['inputs']['user_config']
    old_config=json.loads((pilot.OUTPUT/'execution-root'/old_config_ref['path']).read_text())
    new_config=json.loads((output/'execution-root'/first30.BENCH_REL/'batch/experiments'/CONFIG_NAME).read_text())
    for base,ref in old_config['test_intention']['artifacts'].items():
        if new_config['test_intention']['artifacts'][base]['sha256']!=ref['sha256']:
            raise ValueError('Full run representation differs from the compact pilot')
    write(output/'method-match.json',{'status':'PASS','runtime_matches_pilot':True,
        'pilot_representations_byte_identical':True,'fresh_target_count':90,'new_generation_requests':0})
    references=[first30.DEFAULT_OUTPUT/'host-comparison'/n for n in ('existing-baseline-metrics.json','enhanced-metrics.json')]
    write(output/'comparison-reference-lock.json',{'files':{str(p):first30.sha(p) for p in references},
        'purpose':'Opaque historical report bytes pinned before new Detect; parsed only after the terminal barrier.'})


def prepare(output):
    pilot.prepare(output,config_name=CONFIG_NAME,label=LABEL,expected_count=90)


def run(output):
    pilot.run(output,expected_count=90)


def compare(output):
    references=json.loads((output/'comparison-reference-lock.json').read_text())
    for path,checksum in references['files'].items():
        if Path(path).is_symlink() or first30.sha(Path(path))!=checksum:
            raise ValueError('Historical comparison reference changed during this run')
    pilot.compare(output,expected_count=90,report_path=REPORT)
    pilot.runtime_check(output)
    summary=json.loads((output/'host-comparison/comparison.json').read_text())
    terminal=json.loads((output/'terminal-targets.json').read_text())
    files=[Path(__file__),Path(pilot.__file__),Path(first30.__file__)]
    write(output/'completion.json',{'status':'COMPLETE','authorized_target_count':90,
        'prepared_id':terminal['prepared_id'],
        'sealed_count':sum(v=='DETECT_SEALED' for v in terminal['states'].values()),
        'failed_or_blocked_count':sum(v in {'FAILED','BLOCKED'} for v in terminal['states'].values()),
        'budget_failures':summary['reading']['compact']['token_budget_failures'],
        'paired_input_check':summary['paired_input_check'],'runtime_check':'PASS',
        'new_generation_requests':0,'report':str(REPORT),
        'controller_sha256':{str(p.relative_to(first30.SOURCE_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('setup','prepare','run','compare','all'))
    parser.add_argument('--output',type=Path,default=OUTPUT);args=parser.parse_args()
    steps=('setup','prepare','run','compare') if args.action=='all' else (args.action,)
    for step in steps:
        write(args.output/'execution-status.json',{'stage':step,'state':'RUNNING'})
        print(json.dumps({'stage':step,'state':'STARTED','authorized_targets':90}),flush=True)
        try:globals()[step](args.output)
        except BaseException as exc:
            write(args.output/'execution-status.json',{'stage':step,'state':'FAILED','error':type(exc).__name__+': '+str(exc)})
            raise
        write(args.output/'execution-status.json',{'stage':step,'state':'COMPLETED'})
        print(json.dumps({'stage':step,'state':'COMPLETED'}),flush=True)


if __name__=='__main__':main()
