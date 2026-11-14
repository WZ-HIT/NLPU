"""Real Docker+bubblewrap tool/contract checks; no model credential or requests."""
import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / 'sdd-bench/scrapy-sdd'
PUBLIC = BENCH / 'batch/public_detect'
PLANNING = {'openspec': '/workspace/openspec/changes', 'speckit': '/workspace/specs', 'cc-sdd': '/workspace/.kiro/specs'}


def check(output, bases):
    if output.exists():
        raise ValueError('Use a fresh output directory')
    output.mkdir(parents=True)
    records = []
    security = BENCH / 'tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json'
    for base in bases:
        deployment = json.loads((BENCH / 'batch/images' / base / 'deployment-lock.json').read_text())
        image = deployment['images']['agent']['tag']
        actual = subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True).strip()
        assert actual == deployment['images']['agent']['image_id']
        for method, planning in PLANNING.items():
            fixture = output / base / method
            workspace = fixture / 'workspace'; mount = fixture / 'planning'
            (workspace / planning.removeprefix('/workspace/')).mkdir(parents=True)
            mount.mkdir()
            command = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '1007:1007',
                       '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                       '--security-opt', 'apparmor=scrapy_sdd_codex_parent_11079cb1c85b',
                       '--security-opt', 'seccomp=' + str(security),
                       '--tmpfs', '/tmp:rw,nosuid,nodev,mode=1777,size=256m',
                       '--tmpfs', '/run/sdd-home:rw,nosuid,nodev,mode=0700,uid=1007,gid=1007,size=64m',
                       '--mount', f'type=bind,source={PUBLIC},target=/run/sdd-public,readonly',
                       '--mount', f'type=bind,source={workspace},target=/workspace,readonly',
                       '--mount', f'type=bind,source={mount},target={planning}',
                       '-e', 'HOME=/run/sdd-home', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                       '-e', 'BASH_ENV=/run/sdd-public/shell-env.sh', '--workdir', '/workspace',
                       '--entrypoint', '/opt/agent/bwrap/bin/bwrap', image,
                       '--ro-bind', '/', '/', '--bind', planning, planning, '--tmpfs', '/tmp',
                       '--dev', '/dev', '--proc', '/proc', '--unshare-net', '--',
                       '/usr/local/bin/python3', '/run/sdd-public/probe.py', '--method', method, '--planning', planning]
            result = subprocess.run(command, capture_output=True, text=True, timeout=150)
            try:
                probe = json.loads(result.stdout)
            except ValueError:
                probe = {'pass': False}
            record = {'base': base, 'method': method, 'image_id': actual, 'command': command,
                      'returncode': result.returncode, 'probe': probe, 'stderr': result.stderr[-2000:],
                      'model_requests': 0, 'credential_mounted': False, 'network': 'none'}
            (fixture / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
            records.append(record)
            print(json.dumps({'base': base, 'method': method, 'pass': probe.get('pass'), 'returncode': result.returncode}), flush=True)
    summary = {'targets': len(records), 'passed': sum(r['returncode'] == 0 and r['probe'].get('pass') is True for r in records),
               'model_requests': 0, 'project_tests_run': False, 'records': [str(output / r['base'] / r['method'] / 'result.json') for r in records]}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('output', type=Path); p.add_argument('--base', action='append')
    args = p.parse_args()
    bases = args.base or json.loads(Path('/data2/wangzuohit/NLPU-experiments/test-intention/compact-first30-v1/scope.json').read_text())['base_shas']
    result = check(args.output, bases)
    raise SystemExit(0 if result['targets'] == result['passed'] else 1)
