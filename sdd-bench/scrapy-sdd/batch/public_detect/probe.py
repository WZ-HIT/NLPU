"""No-model runtime probe, callable inside the same sandbox as Agent commands."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from contract import atomic_json, finalize, save_draft, validate, version


def probe(method, planning):
    public = Path(__file__).resolve().parent
    checks = []
    env = dict(os.environ, BASH_ENV=str(public / 'shell-env.sh'))
    for tool in [method if method != 'speckit' else 'specify', 'python3', 'git', 'grep', 'find']:
        command = tool + (' --version' if tool not in {'find'} else ' --version')
        result = subprocess.run(['/bin/bash', '-lc', command], env=env, capture_output=True, text=True, timeout=30)
        checks.append({'tool': tool, 'returncode': result.returncode, 'version_line': (result.stdout or result.stderr).splitlines()[:1]})
    planning = Path(planning)
    if planning.is_symlink() or not planning.is_dir():
        raise ValueError('Planning mount missing or symlink')
    # Neutral source only; no task, labels, model credentials or project tests.
    with tempfile.TemporaryDirectory(prefix='public-detect-source-') as temporary:
        repository = Path(temporary)
        (repository / 'tests').mkdir()
        (repository / 'tests/test_neutral.py').write_text('def test_neutral():\n    assert True\n')
        neutral = {'candidates': [{'path': 'tests/test_neutral.py', 'symbols': ['test_neutral'], 'reason': 'Neutral contract probe'}]}
        with tempfile.TemporaryDirectory(prefix='.sdd-runtime-probe-', dir=planning) as directory:
            save_draft(directory, neutral, [])
            published = finalize(directory, repository)
            checked = validate(json.loads((Path(directory) / 'detection-draft.json').read_text()), repository)
    return {**version(), 'method': method, 'checks': checks, 'planning_writable': True,
            'contract_roundtrip': published['status'] == 'PUBLISHED' and checked['identity_valid'],
            'optional_tools': {name: bool(shutil.which(name)) for name in ['rg', 'curl']},
            'fallback': 'Use git grep/grep/find/python3; do not install rg/curl or contact target PR refs.',
            'model_requests': 0, 'project_tests_run': False,
            'pass': all(c['returncode'] == 0 for c in checks) and checked['identity_valid'] is True}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--method', required=True, choices=['openspec', 'speckit', 'cc-sdd']); p.add_argument('--planning', required=True)
    args = p.parse_args()
    result = probe(args.method, args.planning)
    print(json.dumps(result)); raise SystemExit(0 if result['pass'] else 1)
