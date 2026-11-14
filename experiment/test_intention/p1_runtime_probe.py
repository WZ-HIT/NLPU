"""One pinned-image, read-only Docker+bwrap smoke check; no model/network."""
import json
import subprocess

from .check_p0_runtime import BENCH
from .p1_offline import OUTPUT


def main():
    base = json.loads((OUTPUT/'queries.json').read_text())['tasks'][0]['base_sha']
    bundle = OUTPUT/'representations'/base
    deployment = json.loads((BENCH/'batch/images'/base/'deployment-lock.json').read_text())
    image = deployment['images']['agent']
    actual = subprocess.check_output(['docker', 'image', 'inspect', image['tag'], '--format', '{{.Id}}'], text=True).strip()
    assert actual == image['image_id']
    security = BENCH/'tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json'
    script = '''import contextlib,hashlib,io,json,pathlib,runpy,sys
root=pathlib.Path('/workspace/test-intentions')
sys.path.insert(0,str(root));sys.dont_write_bytecode=True
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
main=runpy.run_path(str(root/'read.py'))['main']
def call(args):
 out=io.StringIO()
 with contextlib.redirect_stdout(out): code=main(args)
 assert code==0,out.getvalue()
 return json.loads(out.getvalue()),len(out.getvalue().encode())
page,size=call(['search','--query','open_in_browser','--search-field','facts.calls'])
assert size<=6000 and page['items']
hit=page['items'][0]
evidence,_=call(['match',hit['id'],'--ref',hit['hit']['ref']])
value=evidence['items'][0]['value']
assert hit['hit']['text']==value[hit['hit']['start']:hit['hit']['end']]
after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
assert before==after
print(json.dumps({'pass':True,'matched_tests':page['matched_test_count'],'search_bytes':size,'lookup_verified':True,'readonly':True}))
'''
    command = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '1007:1007',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
               '--security-opt', 'apparmor=scrapy_sdd_codex_parent_11079cb1c85b',
               '--security-opt', 'seccomp='+str(security), '--tmpfs', '/tmp:rw,nosuid,nodev,mode=1777,size=256m',
               '--mount', f'type=bind,source={bundle},target=/workspace/test-intentions,readonly',
               '--workdir', '/workspace', '--entrypoint', '/opt/agent/bwrap/bin/bwrap', image['tag'],
               '--ro-bind', '/', '/', '--tmpfs', '/tmp', '--dev', '/dev', '--proc', '/proc', '--unshare-net',
               '--', '/usr/local/bin/python3', '-B', '-c', script]
    run = subprocess.run(command, capture_output=True, text=True, timeout=60)
    result = {'base_sha': base, 'image_id': actual, 'command': command, 'returncode': run.returncode,
              'stdout': run.stdout, 'stderr': run.stderr, 'model_requests': 0,
              'network': 'none', 'credential_mounted': False}
    (OUTPUT/'runtime-probe.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'command'}))
    if run.returncode != 0:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
