"""All 162 new B/C inputs and actual sandbox probes; no provider calls."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from . import matched_completion as full, first30
from .stage_b_bundle import checked


def workspace_files(directory):
    result = {}
    for path in directory.rglob('*'):
        relative = path.relative_to(directory)
        if any(p in {'.git', 'test-intentions', '__pycache__'} for p in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError('Unexpected source symlink: ' + str(path))
        if path.is_file(): result[relative.as_posix()] = first30.sha(path)
    return result


def probe(output, row, target):
    root = output / 'execution-root'; bench = root / first30.BENCH_REL
    group, base, method = row['group'], row['base_sha'], row['method']
    task = target['task_manifest'].parent
    workspace = task / 'runs' / method / 'detect/workspace'
    planning_source = task / 'runs' / method / 'detect/planning-artifacts'
    planning = {'openspec': '/workspace/openspec/changes', 'speckit': '/workspace/specs', 'cc-sdd': '/workspace/.kiro/specs'}[method]
    script = root / 'experiment/test_intention/matched_runtime_probe.py'
    security = bench / 'tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json'
    image = full.read(bench / 'batch/images' / base / 'deployment-lock.json')['images']['agent']
    actual = subprocess.check_output(['docker', 'image', 'inspect', image['tag'], '--format', '{{.Id}}'], text=True).strip()
    if actual != image['image_id']: raise ValueError('Image drift')
    command = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '1007:1007', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges:true', '--security-opt', 'apparmor=scrapy_sdd_codex_parent_11079cb1c85b',
               '--security-opt', 'seccomp=' + str(security),
               '--tmpfs', '/tmp:rw,nosuid,nodev,mode=1777,size=256m',
               '--tmpfs', '/run/sdd-home:rw,nosuid,nodev,mode=0700,uid=1007,gid=1007,size=64m',
               '--mount', f'type=bind,source={bench / "batch/public_detect"},target=/run/sdd-public,readonly',
               '--mount', f'type=bind,source={script},target=/run/ti25-probe.py,readonly',
               '--mount', f'type=bind,source={workspace},target=/workspace,readonly',
               '--mount', f'type=bind,source={planning_source},target={planning}',
               '-e', 'HOME=/run/sdd-home', '-e', 'PYTHONDONTWRITEBYTECODE=1',
               '-e', 'BASH_ENV=/run/sdd-public/shell-env.sh', '--workdir', '/workspace',
               '--entrypoint', '/opt/agent/bwrap/bin/bwrap', image['tag'],
               '--ro-bind', '/', '/', '--bind', planning, planning, '--tmpfs', '/tmp', '--dev', '/dev', '--proc', '/proc',
               '--unshare-net', '--', '/usr/local/bin/python3', '/run/ti25-probe.py',
               '--inside', '--group', group, '--method', method, '--planning', planning]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    try: details = json.loads(result.stdout)
    except ValueError: details = {'pass': False, 'stdout': result.stdout[-1500:]}
    record = {'group': group, 'base_sha': base, 'method': method, 'task_id': row['task_id'],
              'image_id': actual, 'returncode': result.returncode, 'probe': details,
              'stderr': result.stderr[-2000:], 'model_requests': 0, 'credentials_mounted': False}
    full.write(output / 'container-probes' / (group + '-' + base + '-' + method + '.json'), record)
    print(json.dumps({'action': 'container_probe', 'group': group, 'base': base, 'method': method,
                      'pass': result.returncode == 0 and details.get('pass')}), flush=True)
    return record


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else full.OUTPUT
    plan, refs, targets = full.prepared(output)
    if (output / 'offline-acceptance.json').exists(): raise ValueError('Already accepted')
    root, bench = first30.execution_environment(output)
    from batch.stages import detect_prompt, matched_material_prompt
    for group in full.GROUPS:
        for method in full.METHODS:
            current = detect_prompt(method, 'testcase-v1') + matched_material_prompt(group)
            previous = (full.PILOT / 'prompts' / (group + '-' + method + '.txt')).read_text()
            # Saved inspection files add a trailing newline; runtime prompt strings do not.
            if previous not in (current, current + '\n'): raise ValueError('Agent prompt differs from pilot')
    rows = []; selected = {}; paired = {}
    for row in plan['targets']:
        if row['pilot']: continue
        _, target = targets[(row['group'], row['task_id'], row['method'])]
        task = target['task_manifest'].parent
        workspace = task / 'runs' / row['method'] / 'detect/workspace'
        bundle = checked(workspace / 'test-intentions')
        source = full.PILOT / 'materials' / row['group'] / row['base_sha'] / 'manifest.json'
        if first30.sha(workspace / 'test-intentions/manifest.json') != first30.sha(source):
            raise ValueError('Prepared material differs from accepted pilot-era package')
        for relative, digest in bundle['source_files'].items():
            if first30.sha(workspace / relative) != digest: raise ValueError('Source changed')
        source_files = workspace_files(workspace)
        key = (row['task_id'], row['method'])
        fingerprint = {'files': source_files, 'task_md': first30.sha(task / 'experiment-inputs/task.md')}
        if key in paired and paired[key] != fingerprint: raise ValueError('B/C input or initial SDD differs')
        paired[key] = fingerprint
        rows.append({'group': row['group'], 'task_id': row['task_id'], 'method': row['method'],
                     'source_files': len(source_files), 'material_manifest': first30.sha(source), 'status': 'PASS'})
        selected.setdefault((row['group'], row['base_sha'], row['method']), (row, target))
    full.write(output / 'prepared-input-verification.json', {'status': 'PASS', 'targets': rows,
               'new_targets': len(rows), 'paired_blocks': len(paired), 'git_administration_excluded': True})
    print(json.dumps({'action': 'input_acceptance', 'targets': len(rows), 'blocks': len(paired)}), flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(probe, output, row, target) for row, target in selected.values()]
        probes = [f.result() for f in futures]
    if any(r['returncode'] != 0 or not r['probe'].get('pass') for r in probes):
        raise ValueError('Actual container probe failed; no model may start')
    key = Path.home() / '.config/sdd-bench/deepseek-api-key'
    if not key.is_file() or key.is_symlink() or key.stat().st_size == 0: raise ValueError('Credentials unavailable')
    full.write(output / 'offline-acceptance.json', {'status': 'PASS', 'at': full.now(),
               'new_targets': len(rows), 'reused_targets': full.REUSED, 'container_combinations': len(probes),
               'execution_lock_sha256': first30.sha(output / 'execution-lock.json'),
               'model_requests': 0, 'credentials_mounted_during_probes': False,
               'agent_prompts_identical_to_pilot': True,
               'prepared_input_verification_sha256': first30.sha(output / 'prepared-input-verification.json'),
               'pilot_closeout_sha256': first30.sha(output / 'pilot-closeout.json')})
    print(json.dumps({'action': 'offline_acceptance', 'status': 'PASS', 'containers': len(probes)}), flush=True)


if __name__ == '__main__':
    main()
