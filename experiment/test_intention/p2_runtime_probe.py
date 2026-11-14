"""P2 pinned-container smoke check; only pure base and public bundle are mounted."""
import json
import subprocess

from .check_p0_runtime import BENCH
from .p2_gate import OUTPUT, BASELINES


def main():
    base=json.loads((OUTPUT/'queries.json').read_text())['tasks'][0]['base_sha']
    bundle=OUTPUT/'representations'/base
    lock=json.loads((BENCH/'batch/images'/base/'deployment-lock.json').read_text())['images']['agent']
    actual=subprocess.check_output(['docker','image','inspect',lock['tag'],'--format','{{.Id}}'],text=True).strip()
    assert actual==lock['image_id']
    security=BENCH/'tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json'
    script='''import contextlib,io,json,pathlib,runpy,sqlite3,sys
root=pathlib.Path('/workspace/test-intentions');sys.path.insert(0,str(root));sys.dont_write_bytecode=True
main=runpy.run_path(str(root/'read.py'))['main']
def call(args):
 out=io.StringIO()
 with contextlib.redirect_stdout(out):code=main(args,repository=pathlib.Path('/base'))
 assert code==0,out.getvalue()
 return json.loads(out.getvalue()),len(out.getvalue().encode())
with sqlite3.connect((root/'.maintenance.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True) as db:
 fact=json.loads(db.execute("SELECT record FROM facts WHERE category='inheritance' ORDER BY id LIMIT 1").fetchone()[0])
page,size=call(['search','--query',fact['text'],'--search-field','maintenance.inheritance'])
assert size<=6000 and page['items']
row=page['items'][0];evidence,_=call(['match',row['id'],'--ref',row['hit']['ref']])
item=evidence['items'][0];fact=item['context']
assert row['hit']['text']==item['value'][row['hit']['start']:row['hit']['end']]
source,_=call(['source',row['id'],'--ref','maintenance:'+fact['id']])
assert source['items']
assert not (root/'__pycache__').exists()
print(json.dumps({'pass':True,'search_bytes':size,'lookup':True,'source_hash_verified':True,'model_requests':0}))
'''
    command=['docker','run','--rm','--network','none','--read-only','--user','1007:1007','--cap-drop','ALL',
             '--security-opt','no-new-privileges:true','--security-opt','apparmor=scrapy_sdd_codex_parent_11079cb1c85b',
             '--security-opt','seccomp='+str(security),'--tmpfs','/tmp:rw,nosuid,nodev,mode=1777,size=256m',
             '--mount',f'type=bind,source={bundle},target=/workspace/test-intentions,readonly',
             '--mount',f'type=bind,source={BASELINES/base/"repository"},target=/base,readonly',
             '--workdir','/workspace','--entrypoint','/opt/agent/bwrap/bin/bwrap',lock['tag'],
             '--ro-bind','/','/','--tmpfs','/tmp','--dev','/dev','--proc','/proc','--unshare-net','--',
             '/usr/local/bin/python3','-B','-c',script]
    run=subprocess.run(command,capture_output=True,text=True,timeout=60)
    record={'base_sha':base,'image_id':actual,'command':command,'returncode':run.returncode,
            'stdout':run.stdout,'stderr':run.stderr,'network':'none','credential_mounted':False,'model_requests':0}
    (OUTPUT/'runtime-probe.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k!='command'}))
    if run.returncode:
        raise SystemExit(1)


if __name__=='__main__':
    main()
