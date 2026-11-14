"""TI-25 actual container/user/bubblewrap checks with no network or model credentials."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys


def inside(group,method,planning):
    sys.dont_write_bytecode=True
    sys.path.insert(0,'/run/sdd-public')
    from probe import probe
    result=probe(method,planning)
    assert result['pass'],result
    assert not Path('/run/secrets/deepseek-api-key').exists()
    assert not Path('/data2/wangzuohit/NLPU-experiments/test-intention').exists()
    root=Path('/workspace/test-intentions')
    if group=='A':
        assert not root.exists()
        result.update(material_absent=True,reader_checks=0)
    else:
        import runpy,sqlite3
        sys.path.insert(0,str(root));main=runpy.run_path(str(root/'read.py'))['main']
        def call(args):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):code=main(args,root=root,repository=Path('/workspace'))
            assert code==0,out.getvalue()
            assert len(out.getvalue().encode())<=6000
            return json.loads(out.getvalue())
        with sqlite3.connect((root/'.evidence.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            identity=db.execute('SELECT id FROM tests ORDER BY id LIMIT 1').fetchone()[0]
            if group=='B':
                assert db.execute("SELECT count(*) FROM tests WHERE intention!='null'").fetchone()[0]==0
                statuses={json.loads(c)['status'] for c, in db.execute('SELECT card FROM tests')}
                assert statuses=={'STATIC_ONLY'}
        returned=call(['search','--query',identity])
        assert returned['items'] and returned['items'][0]['id']==identity
        hit=returned['items'][0]['hit'];original=call(['match',identity,'--ref',hit['ref']])['items'][0]['value']
        assert original[hit['start']:hit['end']]==hit['text']
        assert call(['show',identity])['items']
        assert call(['source',identity])['items']
        assert call(['sensitive',identity])['items']
        assert not (root/'__pycache__').exists()
        # Evidence and code are read-only under the actual UID, not merely by convention.
        try:
            (root/'forbidden-write').write_text('bad')
        except OSError:pass
        else:raise AssertionError('Bundle writable')
        result.update(reader_checks=5,material_group=group,readonly=True)
    result.update(group=group,network='none',model_credentials=False,model_requests=0)
    print(json.dumps(result))


def host(output):
    from .matched_pilot import prepared
    from .stage_b_bundle import write
    from . import first30
    plan,refs,targets=prepared(output);root=output/'execution-root';bench=root/first30.BENCH_REL
    destination=output/'container-probes'
    if destination.exists():raise ValueError('Use a new probe version')
    destination.mkdir();rows=[]
    security=bench/'tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json'
    script=root/'experiment/test_intention/matched_runtime_probe.py'
    selected={}
    for row in plan['targets']:
        selected.setdefault((row['group'],row['base_sha'],row['method']),row)
    for (group,base,method),row in sorted(selected.items()):
        config,target=targets[(group,row['task_id'],method)];task=target['task_manifest'].parent
        workspace=task/'runs'/method/'detect/workspace';planning_source=task/'runs'/method/'detect/planning-artifacts'
        planning={'openspec':'/workspace/openspec/changes','speckit':'/workspace/specs','cc-sdd':'/workspace/.kiro/specs'}[method]
        image=json.loads((bench/'batch/images'/base/'deployment-lock.json').read_text())['images']['agent']
        actual=subprocess.check_output(['docker','image','inspect',image['tag'],'--format','{{.Id}}'],text=True).strip()
        if actual!=image['image_id']:raise ValueError('Image drift')
        command=['docker','run','--rm','--network','none','--read-only','--user','1007:1007','--cap-drop','ALL',
            '--security-opt','no-new-privileges:true','--security-opt','apparmor=scrapy_sdd_codex_parent_11079cb1c85b',
            '--security-opt','seccomp='+str(security),
            '--tmpfs','/tmp:rw,nosuid,nodev,mode=1777,size=256m',
            '--tmpfs','/run/sdd-home:rw,nosuid,nodev,mode=0700,uid=1007,gid=1007,size=64m',
            '--mount',f'type=bind,source={bench/"batch/public_detect"},target=/run/sdd-public,readonly',
            '--mount',f'type=bind,source={script},target=/run/ti25-probe.py,readonly',
            '--mount',f'type=bind,source={workspace},target=/workspace,readonly',
            '--mount',f'type=bind,source={planning_source},target={planning}',
            '-e','HOME=/run/sdd-home','-e','PYTHONDONTWRITEBYTECODE=1',
            '-e','BASH_ENV=/run/sdd-public/shell-env.sh','--workdir','/workspace',
            '--entrypoint','/opt/agent/bwrap/bin/bwrap',image['tag'],
            '--ro-bind','/','/','--bind',planning,planning,'--tmpfs','/tmp','--dev','/dev','--proc','/proc','--unshare-net','--',
            '/usr/local/bin/python3','/run/ti25-probe.py','--inside','--group',group,'--method',method,'--planning',planning]
        result=subprocess.run(command,capture_output=True,text=True,timeout=150)
        try:probe=json.loads(result.stdout)
        except ValueError:probe={'pass':False}
        record={'group':group,'base_sha':base,'method':method,'task_id':row['task_id'],'image_id':actual,
            'returncode':result.returncode,'probe':probe,'stderr':result.stderr[-3000:],'command':command,
            'model_requests':0,'credential_mounted':False}
        write(destination/(group+'-'+base+'-'+method+'.json'),record);rows.append(record)
        print(json.dumps({k:record[k] for k in ('group','base_sha','method','returncode')}),flush=True)
    summary={'status':'PASS' if all(r['returncode']==0 and r['probe'].get('pass') for r in rows) else 'FAILED',
             'containers':len(rows),'passed':sum(r['returncode']==0 and bool(r['probe'].get('pass')) for r in rows),
             'actual_user':'1007:1007','network':'none','model_requests':0,'credential_mounted':False,
             'coverage':'two pilot bases x three SDD x three groups; all 27 prepared task paths additionally audited'}
    write(destination/'summary.json',summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inside',action='store_true')
    p.add_argument('--group');p.add_argument('--method');p.add_argument('--planning');p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.inside:inside(args.group,args.method,args.planning)
    else:
        from .matched_materials import OUTPUT
        result=host(args.output or OUTPUT)
        if result['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
