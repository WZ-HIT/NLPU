"""One authorized enhanced-only first-30 experiment; historical sources are read-only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading

from .static import write

SOURCE_ROOT = Path(__file__).resolve().parents[2]
BENCH_REL = Path('sdd-bench/scrapy-sdd')
DEFAULT_OUTPUT = Path('/data2/wangzuohit/NLPU-experiments/test-intention/first30-v1')
CONFIG_NAME = 'scrapy-30pr-test-intention-v1.json'
ROUND_LABEL = 'test-intention-first30-001'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mirror(output):
    """Copy host-only frozen dependencies by identity; never expose their contents."""
    root = output / 'execution-root'
    root.mkdir(parents=True, exist_ok=True)
    bench = root / BENCH_REL
    source_bench = SOURCE_ROOT / BENCH_REL
    scope = json.loads((output / 'scope.json').read_text())

    def copy(relative):
        relative = Path(relative)
        source = SOURCE_ROOT / relative
        target = root / relative
        if source.is_symlink() or '..' in relative.parts or relative.is_absolute():
            raise ValueError('Unsafe host dependency')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or sha(target) != sha(source):
            if target.exists():
                target.chmod(0o644)
            shutil.copy2(source, target)
        if sha(target) != sha(source):
            raise ValueError('Copied host dependency hash mismatch')

    for p in (source_bench / 'batch').rglob('*.py'):
        rel = p.relative_to(source_bench / 'batch')
        if len(rel.parts) == 1 or rel.parts[0] in {'archive', 'tests'}:
            copy(p.relative_to(SOURCE_ROOT))
    for folder in ('schemas', 'adapters', 'bin'):
        shutil.copytree(source_bench / folder, bench / folder, dirs_exist_ok=True)
    shutil.copytree(source_bench / 'batch/public_detect', bench / 'batch/public_detect',
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    copy(BENCH_REL / 'tools/sdd-results.py')
    for folder in ('environments/network/haproxy-3.2.23',
                   'environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates'):
        shutil.copytree(source_bench / folder, bench / folder, dirs_exist_ok=True)

    config_relative = BENCH_REL / 'batch/experiments/scrapy-30pr-testcase-v1.json'
    copy(config_relative)
    config = json.loads((SOURCE_ROOT / config_relative).read_text())
    for reference in config['sources']:
        copy(reference['path'])
        source = json.loads((SOURCE_ROOT / reference['path']).read_text())
        approved = source['approved_plan']
        for key in ('path', 'provision_report_path'):
            copy(approved[key])
        plan = json.loads((SOURCE_ROOT / approved['path']).read_text())
        for reference in (*plan['inputs'].values(), plan['inventory']):
            copy(reference['path'])  # Opaque bytes: raw/prompt are host-only, never model packets.
        for task in source['tasks']:
            copy(task['task_manifest']['path'])
    for base in scope['base_shas']:
        source = source_bench / 'batch/baselines' / base
        target = bench / 'batch/baselines' / base
        if not (target / 'baseline-lock.json').exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['rsync', '-a', str(source) + '/', str(target) + '/'], check=True)
        for relative in (f'batch/images/{base}/deployment-lock.json', f'batch/audits/images/{base}-image-audit.json'):
            copy(BENCH_REL / relative)

    reference_task = BENCH_REL / 'tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba'
    evidence = BENCH_REL / 'Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits'
    lists = {'openspec': 'openspec-init-formal-12/step12-formal-hashes.txt',
             'speckit': 'speckit-init-formal-16/generated-files.sha256',
             'cc-sdd': 'cc-sdd-init-formal-20/generated-files.sha256'}
    for method, name in lists.items():
        copy(evidence / name)
        for line in (SOURCE_ROOT / evidence / name).read_text().splitlines():
            checksum, relative = line.split('  ', 1)
            path = reference_task / 'runs' / method / 'scrapy' / relative
            copy(path)
            if sha(root / path) != checksum:
                raise ValueError('Initialization hash mismatch')
    for name in ('apparmor-codex-bwrap-0.12.0.draft', 'seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json'):
        copy(reference_task / name)
    print(json.dumps({'execution_root': str(root), 'mirrored_bases': len(scope['base_shas'])}), flush=True)
    return root


def install_representations(output):
    root = output / 'execution-root'
    scope = json.loads((output / 'scope.json').read_text())
    config = json.loads((root / BENCH_REL / 'batch/experiments/scrapy-30pr-testcase-v1.json').read_text())
    artifacts = {}
    for base in scope['base_shas']:
        source = output / 'representations' / base
        destination = root / 'experiment-artifacts/test-intention' / base / sha(source / 'manifest.json')
        if destination.exists():
            from batch.test_intention import verify_bundle
            verify_bundle(destination / 'manifest.json', base)
            if sha(destination / 'manifest.json') != sha(source / 'manifest.json'):
                raise ValueError('Frozen representation source differs')
        else:
            shutil.copytree(source, destination)
        path = destination / 'manifest.json'
        artifacts[base] = {'path': path.relative_to(root).as_posix(), 'sha256': sha(path)}
    config['experiment_id'] = 'scrapy-30pr-test-intention-v1'
    config['test_intention'] = {'entrypoint': 'test-intentions/README.md', 'artifacts': artifacts}
    path = root / BENCH_REL / 'batch/experiments' / CONFIG_NAME
    write(path, config)
    return path


def execution_environment(output):
    root = (output / 'execution-root').resolve()
    bench = root / BENCH_REL
    sys.path.insert(0, str(bench))
    temporary = output / 'tmp'
    temporary.mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(temporary)
    os.environ['SDD_PREFLIGHT_TMPDIR'] = str(temporary)
    import tempfile
    tempfile.tempdir = str(temporary)
    return root, bench


def prepare(output):
    root, bench = execution_environment(output)
    from batch.rounds import prepare_round
    path = install_representations(output)
    frozen = prepare_round(path, ROUND_LABEL, root=root)
    write(output / 'prepared-reference.json', {'prepared_id': frozen['prepared_id'],
        'manifest': str(bench / 'batch/runs' / frozen['prepared_id'] / 'prepared-round.json'),
        'target_count': frozen['target_count']})
    print(json.dumps({'prepared_id': frozen['prepared_id'], 'target_count': frozen['target_count']}), flush=True)


def run(output, *, expected_count=90, before_detect=None):
    """Three method queues; one ledger writer, no retries of failed formal targets."""
    root, bench = execution_environment(output)
    from batch.core import BatchError
    from batch.orchestrator import Ledger, _latest, target_key, validate_prepared_manifest, _run_duration_lock
    from batch.stages import detect_targets
    reference = json.loads((output / 'prepared-reference.json').read_text())
    path = Path(reference['manifest'])
    config, targets = validate_prepared_manifest(path, bench, root)
    if len(targets) != expected_count or {t['stage'] for t in targets} != {'detect'}:
        raise ValueError('Expected the authorized direct Detect target count')
    scope = json.loads((output / 'scope.json').read_text())
    if {(t['task_id'], t['method']) for t in targets} != {(t['task_id'], t['method']) for t in scope['targets']}:
        raise ValueError('Prepared targets differ from the authorized scope')
    run_root = path.parent
    with _run_duration_lock(run_root, config['batch_id']):
        ledger = Ledger(run_root / 'ledger.jsonl', config['batch_id'], bench / 'schemas/batch-ledger-event-v1.schema.json')
        latest = _latest(ledger.read())
        selected = [t for t in targets if latest.get(target_key(t), {}).get('state') not in {'DETECT_SEALED', 'FAILED', 'BLOCKED'}]
        if any(latest.get(target_key(t), {}).get('state') == 'DETECT_RUNNING' for t in selected):
            raise ValueError('Interrupted running target requires inspection; no automatic rerun')
        events = queue.Queue()
        stopped = threading.Event()

        def worker(method):
            try:
                for target in selected:
                    if target['method'] != method or stopped.is_set():
                        continue
                    acknowledged = threading.Event()
                    events.put(('start', target, acknowledged))
                    while not acknowledged.wait(1):
                        if stopped.is_set():
                            return
                    if stopped.is_set():
                        return
                    destination = target['task_manifest'].parent / 'runs' / method / 'detect/executions' / target['run_id'] / 'attempt-1'
                    try:
                        if before_detect:
                            before_detect(target)
                        result = detect_targets(task_manifest=target['task_manifest'], method=method,
                            run_id=target['run_id'], output=destination, bench=bench, repository_root=root,
                            dry_run=False, localization_protocol='testcase-v1')
                        events.put(('DETECT_SEALED', target, result))
                    except Exception as exc:
                        error = exc.as_dict() if isinstance(exc, BatchError) else {'message': str(exc)}
                        events.put(('FAILED', target, {'error': error}))
            finally:
                events.put(('finished', method, None))

        finished, completed = 0, len(targets) - len(selected)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(worker, method) for method in ('openspec', 'speckit', 'cc-sdd')]
            while finished < 3:
                try:
                    action, target, result = events.get(timeout=30)
                except queue.Empty:
                    print(json.dumps({'completed': completed, 'target_count': len(targets), 'status': 'RUNNING'}), flush=True)
                    continue
                if action == 'finished':
                    finished += 1
                elif action == 'start':
                    try:
                        for state in ('PLANNED', 'PREFLIGHT_READY', 'DETECT_RUNNING'):
                            ledger.append('detect', target, state, 1, {'target': target_key(target)})
                    except BaseException:
                        stopped.set()
                        raise
                    result.set()  # Worker may call the model only after durable start.
                else:
                    try:
                        detail_path = run_root / 'execution-events' / (target['task_id'] + '-' + target['method'] + '-' + action + '.json')
                        write(detail_path, result)
                        ledger.append('detect', target, action, 1, result)
                    except BaseException:
                        stopped.set()
                        raise
                    completed += 1
                    print(json.dumps({'completed': completed, 'target_count': len(targets), 'method': target['method'],
                                      'task_id': target['task_id'], 'state': action}), flush=True)
            for future in futures:
                future.result()
        latest = _latest(ledger.read())
        states = {target_key(t): latest.get(target_key(t), {}).get('state') for t in targets}
        if not all(state in {'DETECT_SEALED', 'FAILED', 'BLOCKED'} for state in states.values()):
            raise ValueError('All-target terminal barrier did not pass')
        write(output / 'terminal-targets.json', {'prepared_id': config['batch_id'], 'states': states,
             'target_count': len(states), 'ledger_sha256': sha(run_root / 'ledger.jsonl')})


def compare(output):
    """Host-only phase, permitted only after all new predictions have terminated."""
    root, bench = execution_environment(output)
    terminal = json.loads((output / 'terminal-targets.json').read_text())
    run_root = bench / 'batch/runs' / terminal['prepared_id']
    if terminal['target_count'] != 90 or terminal['ledger_sha256'] != sha(run_root / 'ledger.jsonl'):
        raise ValueError('Terminal prediction barrier is missing or stale')
    from batch.testcase_metrics import compute
    current = compute(bench, terminal['prepared_id'])
    # Gold and per-test predictions stay in these host files; stdout is aggregate-only.
    report = output / 'host-comparison'
    report.mkdir(parents=True, exist_ok=True, mode=0o700)
    report.chmod(0o700)
    write(report / 'enhanced-metrics.json', current)
    source_bench = SOURCE_ROOT / BENCH_REL
    previous = compute(source_bench, 'round-65f66ff1426e4c7d1f8da662')
    write(report / 'existing-baseline-metrics.json', previous)
    old_rows = {(r['task_id'], r['method']): r for r in previous['rows']}
    new_rows = {(r['task_id'], r['method']): r for r in current['rows']}
    scope = json.loads((output / 'scope.json').read_text())
    expected = {(t['task_id'], t['method']) for t in scope['targets']}
    if len(old_rows) != 90 or len(new_rows) != 90 or set(old_rows) != expected or set(new_rows) != expected:
        raise ValueError('Comparison requires exactly the authorized 90 paired targets')
    for row in current['rows']:
        old = old_rows[(row['task_id'], row['method'])]
        allowed = {'OK', 'FAILED_ZERO', 'NO_POSITIVE_GOLD'}
        if row['status'] not in allowed or old['status'] not in allowed:
            raise ValueError('Invalid or incomplete evaluation evidence; comparison stopped')
        if (row['testcase'] is None) != (old['testcase'] is None):
            raise ValueError('Paired scoreable denominator differs')
        if (row['index_sha256'], row['labels_sha256']) != (old['index_sha256'], old['labels_sha256']):
            raise ValueError('Paired source inventory or label identity differs')
    frozen = json.loads((run_root / 'prepared-round.json').read_text())
    original_tasks = {t['task_id']: t['task_manifest']['sha256'] for t in scope['targets']}
    if any(t['task_manifest']['sha256'] != original_tasks[t['task_id']] for t in frozen['targets']):
        raise ValueError('Paired public task title/body/base snapshot differs')
    per_pr = []
    for identity in sorted(new_rows):
        new, old = new_rows[identity], old_rows[identity]
        delta = ({key: new['testcase'][key] - old['testcase'][key]
                  for key in ('tp', 'fp', 'fn', 'precision', 'recall', 'f1')}
                 if new['testcase'] is not None else None)
        per_pr.append({'task_id': identity[0], 'method': identity[1],
                       'baseline_status': old['status'], 'enhanced_status': new['status'],
                       'baseline': old['testcase'], 'enhanced': new['testcase'], 'difference': delta})
    write(report / 'per-pr-differences.json', per_pr)
    differences = []
    common_success = []
    for new in current['methods']:
        old = next(m for m in previous['methods'] if m['method'] == new['method'])
        delta = {key: new['testcase'][key] - old['testcase'][key]
                 for key in ('precision_macro', 'recall_macro', 'f1_macro', 'precision_micro', 'recall_micro', 'f1_micro')
                 if new['testcase'][key] is not None and old['testcase'][key] is not None}
        differences.append({'method': new['method'], 'baseline': old['testcase'],
                            'enhanced': new['testcase'], 'difference': delta,
                            'recall_changes': {label: sum(
                                1 for row in per_pr if row['method'] == new['method'] and row['difference'] is not None
                                and comparison(row['difference']['recall']))
                                for label, comparison in (('improved', lambda d: d > 0), ('unchanged', lambda d: d == 0), ('decreased', lambda d: d < 0))},
                            'baseline_statuses': old['statuses'], 'enhanced_statuses': new['statuses']})
        matched = [row for row in per_pr if row['method'] == new['method']
                   and row['baseline_status'] == row['enhanced_status'] == 'OK']
        common_success.append({'method': new['method'], 'count': len(matched),
            'recall_macro_baseline': sum(row['baseline']['recall'] for row in matched) / len(matched) if matched else None,
            'recall_macro_enhanced': sum(row['enhanced']['recall'] for row in matched) / len(matched) if matched else None})
    result = {'paired_input_check': 'PASS', 'pr_count': 30, 'target_count': 90,
              'baseline_round': previous['batch_id'], 'enhanced_round': current['batch_id'],
              'baseline_counts': previous['counts'], 'enhanced_counts': current['counts'], 'methods': differences,
              'both_successful_secondary_analysis': common_success,
              'interpretation_limit': 'Historical model configuration bytes were not independently pinned; changes in success rates and runtime may also affect scores.'}
    # Recompute aggregates from the per-target counts without the benchmark
    # summarize function; a mismatched denominator or arithmetic stops reporting.
    for name, document in (('baseline', previous), ('enhanced', current)):
        for method in document['methods']:
            rows = [r['testcase'] for r in document['rows'] if r['method'] == method['method'] and r['testcase'] is not None]
            totals = {key: sum(row[key] for row in rows) for key in ('tp', 'fp', 'fn')}
            tp, fp, fn = (totals[key] for key in ('tp', 'fp', 'fn'))
            values = {'precision_micro': tp/(tp+fp) if tp+fp else 0.,
                      'recall_micro': tp/(tp+fn) if tp+fn else 0.,
                      'f1_micro': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.}
            values.update({key+'_macro': sum(row[key] for row in rows)/len(rows)
                           for key in ('precision', 'recall', 'f1')})
            if method['testcase']['scored_count'] != len(rows) or any(
                    abs(method['testcase'][key] - value) > 1e-12 for key, value in values.items()):
                raise ValueError('Independent aggregate verification failed: ' + name)
    write(report / 'independent-verification.json', {'status': 'PASS', 'paired_targets': 90,
        'checks': ['exact public task snapshots', 'same source test indexes', 'same labels',
                   'valid prediction seals or failed-zero', 'identical scoreable denominator',
                   'independent precision/recall/F1 arithmetic from per-target counts']})
    write(report / 'comparison.json', result)
    lines = ['# 首批 30 个 PR：测试行为表示实验结果', '',
             '范围：30 个 PR × 三种 SDD；仅运行新的增强组，原组复用已有结果。', '',
             '| SDD | 原 macro recall | 新 macro recall | 差值（百分点） | 原 macro precision | 新 macro precision | 原 macro F1 | 新 macro F1 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for method in differences:
        old, new = method['baseline'], method['enhanced']
        lines.append('| ' + method['method'] + ' | ' + ' | '.join([
            f"{old['recall_macro']*100:.2f}%", f"{new['recall_macro']*100:.2f}%",
            f"{method['difference']['recall_macro']*100:+.2f}",
            f"{old['precision_macro']*100:.2f}%", f"{new['precision_macro']*100:.2f}%",
            f"{old['f1_macro']*100:.2f}%", f"{new['f1_macro']*100:.2f}%"]) + ' |')
    lines.extend(['', '失败项按零分保留，无正例任务单列；具体计分数量、micro 指标和逐 PR 差值见同目录 JSON。', '',
        '输入、标签与算术独立核查通过。历史实际模型配置字节未独立固定，运行成功率变化也可能影响指标，不能把所有差值归因于表示。'])
    (report / 'report.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action', choices=('mirror', 'prepare', 'run', 'compare'))
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    globals()[args.action](args.output.resolve())


if __name__ == '__main__':
    main()
