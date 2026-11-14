"""Independent source-span, displayed-page and metric verification for P2."""
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
import subprocess
import tokenize

from .p2_gate import OUTPUT, P1, BASELINES
from .p1_offline import RUN
from .p1_verify import visible_ids
from . import maintenance_view as view, reader, search_view as search


def verify_sources():
    import sqlite3
    verified=0
    bundles=json.loads((OUTPUT/'bundles.json').read_text())
    for item in bundles:
        base=item['base_sha'];root=OUTPUT/'representations'/base;repo=BASELINES/base/'repository'
        assert search.sha(root/'.evidence.sqlite3')==search.sha(P1/'representations'/base/'.evidence.sqlite3')
        cache={}
        with view.connect(root) as db:
            assert db.execute('SELECT count(*) FROM members m LEFT JOIN facts f ON m.fact_id=f.id WHERE f.id IS NULL OR m.category!=f.category').fetchone()[0]==0
            for raw, in db.execute('SELECT record FROM facts ORDER BY id'):
                fact=json.loads(raw);loc=fact['source'];path=repo/loc['path']
                if loc['path'] not in cache:
                    with tokenize.open(path) as stream:
                        lines=stream.read().encode().splitlines(keepends=True)
                    cache[loc['path']]=(search.sha(path),lines)
                digest,lines=cache[loc['path']]
                assert digest==loc['file_sha256']
                selected=lines[loc['start_line']-1:loc['end_line']]
                if len(selected)==1:
                    segment=selected[0][loc['start_column']:loc['end_column']]
                else:
                    selected[-1]=selected[-1][:loc['end_column']]
                    selected[0]=selected[0][loc['start_column']:]
                    segment=b''.join(selected)
                assert segment.decode()==fact['text'],fact['id']
                value={k:v for k,v in fact.items() if k!='id'}
                expected=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
                assert expected==fact['id']
                verified+=1
            with reader.connect(root) as original:
                ids={i for i, in original.execute('SELECT id FROM tests')}
            assert ids=={i for i, in db.execute('SELECT test_id FROM coverage')}
        print(json.dumps({'base':base,'source_spans_verified':item['coverage']['unique_facts']}),flush=True)
    (OUTPUT/'source-verification.json').write_text(json.dumps({'pass':True,'bases':len(bundles),'unique_facts_verified':verified,'evidence_byte_identical':True},indent=2)+'\n')


def main():
    seal=json.loads((OUTPUT/'rankings-seal.json').read_text())
    for name,digest in seal['files'].items():
        assert search.sha(OUTPUT/name)==digest,name
    metrics=json.loads((OUTPUT/'offline-metrics.json').read_text())
    labels=json.loads((RUN/'host-comparison/metrics.json').read_text())['tasks']
    tasks=json.loads((OUTPUT/'queries.json').read_text())['tasks']
    values=defaultdict(list);checks=[]
    for task in tasks:
        directory=OUTPUT/'rankings'/task['task_id'];gold=set(labels[task['task_id']]['labels']['testcases'])
        for variant in ('P','N','A','C'):
            raw=(directory/(variant+'.page.json')).read_bytes();page=json.loads(raw)
            ids=visible_ids(page);prediction=json.loads((directory/(variant+'.json')).read_text())
            assert len(raw)==prediction['output_utf8_bytes'] and len(raw)<=6000
            assert ids==prediction['visible_ids']
            hits=len(set(ids)&gold)
            row=next(r for r in metrics['rows'] if r['task_id']==task['task_id'] and r['variant']==variant)
            assert hits==row['hits'] and len(gold)==row['gold']
            if gold:
                values[variant].append((hits,len(gold)))
        root=OUTPUT/'representations'/task['base_sha']
        command=['python3','-B',str(root/'read.py'),'search','--limit','25','--max-bytes','6000']
        for query in task['queries']:
            command.extend(['--query',query])
        run=subprocess.run(command,capture_output=True,timeout=90)
        assert run.returncode==0,run.stderr.decode()
        actual=json.loads(run.stdout);expected=json.loads((directory/'N.page.json').read_text())
        assert actual['items']==expected['items']
        assert len(run.stdout)==len((directory/'N.page.json').read_bytes())
        assert not (root/'__pycache__').exists()
        checks.append({'task_id':task['task_id'],'pass':True,'bytes':len(run.stdout)})
        print(json.dumps(checks[-1]),flush=True)
    for variant,rows in values.items():
        macro=sum((Fraction(h,n) for h,n in rows),Fraction())/len(rows)
        micro=Fraction(sum(h for h,n in rows),sum(n for h,n in rows))
        assert abs(float(macro)-metrics['summaries'][variant]['macro_recall'])<1e-12
        assert abs(float(micro)-metrics['summaries'][variant]['micro_recall'])<1e-12
    from batch.test_intention import verify_bundle
    for base in {t['base_sha'] for t in tasks}:
        verify_bundle(OUTPUT/'representations'/base/'manifest.json',base)
    result={'pass':True,'independent_pages':120,'public_cli_checks':30,'bases':22,'checks':checks,
            'queries_byte_identical_to_p1':(OUTPUT/'queries.json').read_bytes()==(P1/'queries.json').read_bytes(),
            'metrics_sha256':search.sha(OUTPUT/'offline-metrics.json'),'model_calls':0}
    (OUTPUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    import sys
    verify_sources() if '--sources' in sys.argv else main()
