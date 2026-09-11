"""04i probe: run only in a disposable, network-disabled baseline container.

Mount this script and one tool's artifacts read-only under /inputs; mount a
dedicated report directory at /output. Never mount an experiment workspace.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

tool = sys.argv[1]
assert tool in ('openspec', 'cc-sdd', 'speckit')
report = {'tool': tool, 'status': 'running', 'commands': []}
inputs = Path('/inputs/tool')
probe = Path('/tmp/probe')
probe.mkdir()
Path('/tmp/home').mkdir(exist_ok=True)
os.chdir(probe)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(argv, cwd=None):
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=180)
    report['commands'].append({'argv': argv, 'exit_code': result.returncode,
                               'stdout': result.stdout, 'stderr': result.stderr})
    if result.returncode:
        raise RuntimeError(f'{argv}: exit {result.returncode}: {result.stderr[-2000:]}')
    return result.stdout.strip()


def baseline():
    raw = run(['/usr/local/bin/python', '-m', 'pip', 'freeze', '--all'])
    entries = sorted(raw.splitlines())
    checksum = hashlib.sha256(('\n'.join(entries) + '\n').encode()).hexdigest()
    assert len(entries) == 69
    assert checksum == '570e1651694fe0e30bbd07a231c2f70cccf09cd18503b8ead34fdfd50f5f3abd'
    run(['/usr/local/bin/python', '-m', 'pip', 'check'])
    return {'count': len(entries), 'sha256': checksum}


try:
    assert sys.version_info[:3] == (3, 11, 15)
    report['python'] = sys.version.split()[0]
    report['baseline_before'] = baseline()
    archive = Path('/inputs/node.tar.xz')
    assert digest(archive) == '2f2c0da162318f0de47665410c7c8c2ed3d36c8f3105de4bbc61176c70a7cbf2'
    with tarfile.open(archive) as tar:
        tar.extractall('/tmp/node', filter='data')
    os.environ['PATH'] = '/tmp/node/node-v24.20.0-linux-x64/bin:/usr/local/bin:/usr/bin:/bin'
    os.environ.update(NPM_CONFIG_CACHE='/tmp/npm-cache',
                      NPM_CONFIG_PREFIX='/tmp/home/tools/npm',
                      NPM_CONFIG_USERCONFIG='/tmp/user.npmrc',
                      NPM_CONFIG_GLOBALCONFIG='/tmp/global.npmrc',
                      NPM_CONFIG_UPDATE_NOTIFIER='false',
                      NPM_CONFIG_AUDIT='false', NPM_CONFIG_FUND='false',
                      UV_CACHE_DIR='/tmp/uv-cache', UV_NO_CONFIG='1',
                      UV_PYTHON_DOWNLOADS='never', NO_COLOR='1')
    report['node'] = run(['node', '--version'])
    report['npm'] = run(['npm', '--version'])
    assert report['node'] == 'v24.20.0' and report['npm'] == '11.19.0'
    if tool in ('openspec', 'cc-sdd'):
        manifest = json.loads((inputs / 'npm-artifacts/artifact-manifest.json').read_text())
        assert digest(inputs / 'package-lock.json') == manifest['package_lock_sha256']
        artifacts = inputs / 'npm-artifacts'
        for entry in manifest['artifacts']:
            path = artifacts / entry['file']
            assert path.resolve().parent == artifacts.resolve()
            assert digest(path) == entry['sha256'] and path.stat().st_size == entry['size_bytes']
            run(['npm', 'cache', 'add', str(path), '--offline', '--ignore-scripts'])
        target = Path('/tmp/npm-tool')
        target.mkdir()
        for name in ('package.json', 'package-lock.json'):
            shutil.copyfile(inputs / name, target / name)
        run(['npm', 'ci', '--offline', '--ignore-scripts', '--engine-strict',
             '--no-audit', '--no-fund', '--registry=https://registry.npmjs.org/'], cwd=target)
        for name in ('package.json', 'package-lock.json'):
            assert digest(inputs / name) == digest(target / name)
        lock = json.loads((inputs / 'package-lock.json').read_text())
        for path, entry in lock['packages'].items():
            if path:
                installed = json.loads((target / path / 'package.json').read_text())
                assert installed['version'] == entry['version'], path
        report['installed_package_entries'] = len(lock['packages']) - 1
        run(['npm', 'ls', '--all', '--json'], cwd=target)
        executable = str(target / 'node_modules/.bin' / tool)
        report['version_output'] = run([executable, '--version'])
        expected = '1.12.0' if tool == 'openspec' else 'cc-sdd v3.0.2'
        assert report['version_output'] == expected, report['version_output']
        help_text = run([executable, '--help'])
        assert '--help' in help_text
    else:
        manifest = json.loads((inputs / 'artifact-manifest.json').read_text())
        for entry in manifest['artifacts']:
            path = inputs / entry['path']
            assert path.resolve().is_relative_to(inputs.resolve())
            assert digest(path) == entry['sha256'] and path.stat().st_size == entry['size_bytes']
        assert digest('/inputs/uv.tar.gz') == '173d95a0c32d18c896c46ba6fafbf3cf9c14ab74b033f81b76c883ef492a976b'
        with tarfile.open('/inputs/uv.tar.gz') as tar:
            tar.extractall('/tmp/uv', filter='data')
        uv = '/tmp/uv/uv-x86_64-unknown-linux-gnu/uv'
        report['uv'] = run([uv, '--version'])
        assert report['uv'].split()[:2] == ['uv', '0.12.10']
        run([uv, 'venv', '--python', '/usr/local/bin/python', '/tmp/tool-env'])
        run([uv, 'pip', 'sync', str(inputs / 'install-requirements.txt'),
             '--python', '/tmp/tool-env/bin/python', '--offline', '--no-index',
             '--find-links', str(inputs / 'dist'), '--find-links', str(inputs / 'wheels'),
             '--require-hashes', '--no-build'])
        run([uv, 'pip', 'check', '--python', '/tmp/tool-env/bin/python', '--offline'])
        packages = json.loads(run([uv, 'pip', 'list', '--python', '/tmp/tool-env/bin/python', '--format=json', '--offline']))
        assert len(packages) == 15
        assert not any(p['name'] == 'hatchling' for p in packages)
        assert 'include-system-site-packages = false' in Path('/tmp/tool-env/pyvenv.cfg').read_text()
        report['installed_package_entries'] = len(packages)
        report['version_output'] = run(['/tmp/tool-env/bin/specify', '--version'])
        assert report['version_output'] == 'specify 1.0.4'
        help_text = run(['/tmp/tool-env/bin/specify', '--help'])
        assert 'Usage:' in help_text
    assert not list(probe.iterdir()), 'A version/help probe wrote into the working directory'
    report['baseline_after'] = baseline()
    report['empty_probe_directory'] = True
    report['status'] = 'passed'
except Exception as error:
    report['status'] = 'failed'
    report['error'] = repr(error)
    raise
finally:
    destination = Path('/output') / (tool + '.json')
    with destination.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'commands'}, indent=2))
