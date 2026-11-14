"""TI-26 closeout and TI-27 B/C continuation; old pilot predictions remain immutable."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import queue
import random
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading

from . import first30, matched_pilot
from .stage_b_bundle import checked

PILOT = Path('/data2/wangzuohit/NLPU-experiments/test-intention/stage-c-20261109-v1')
OUTPUT = PILOT.parent / 'stage-c-bc-20261110-v1'
DESIGN = PILOT.parent / 'ti13-14-20261104-v1/design'
GROUPS = ('B', 'C')
METHODS = ('openspec', 'speckit', 'cc-sdd')
TOTAL = 180
NEW = 162
REUSED = 18
TERMINAL = matched_pilot.TERMINAL
RUNTIME = first30.BENCH_REL / 'environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates'


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)


def refusal(text):
    value = text.casefold()
    return any(s in value for s in ('insufficient balance', 'insufficient_balance',
                                    'invalid api key', 'invalid_api_key'))


def execution(root, target):
    return root / target['task_manifest']['path'] if isinstance(target['task_manifest'], dict) else target['task_manifest']


def log_audit(root, target):
    task = execution(root, target)
    directory = task.parent / 'runs' / target['method'] / 'detect/executions' / target['run_id'] / 'attempt-1'
    log = directory / 'agent.jsonl'
    result = {'task_id': target['task_id'], 'method': target['method'],
              'execution': str(directory), 'log_exists': log.exists(), 'commands': 0,
              'tool_errors': [], 'reader_commands': 0, 'decision_commands': 0,
              'semantic_read_commands': 0, 'terminal_events': [], 'usage': None, 'invalid_jsonl_lines': 0}
    if not log.exists():
        return result
    result['agent_sha256'] = first30.sha(log)
    usage = []
    for number, line in enumerate(log.read_text().splitlines(), 1):
        try:
            event = json.loads(line)
        except ValueError:
            result['invalid_jsonl_lines'] += 1
            continue
        if not isinstance(event, dict):
            result['invalid_jsonl_lines'] += 1
            continue
        if event.get('type') in ('turn.completed', 'turn.failed', 'error'):
            result['terminal_events'].append({'line': number, 'type': event['type']})
        if event.get('type') == 'turn.completed' and isinstance(event.get('usage'), dict):
            usage.append(event['usage'])
        item = event.get('item', {})
        if event.get('type') != 'item.completed' or item.get('type') != 'command_execution':
            continue
        command = item.get('command', '')
        result['commands'] += 1
        result['reader_commands'] += 'test-intentions/read.py' in command
        result['decision_commands'] += '/decisions.py' in command
        result['semantic_read_commands'] += bool(re.search(r'read\.py\s+(scenarios|detail)\b', command))
        if item.get('exit_code') not in (None, 0):
            result['tool_errors'].append({'line': number, 'exit_code': item['exit_code'],
                                         'command': command[:700]})
    keys = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')
    if usage and all(isinstance(u.get('input_tokens'), int) and isinstance(u.get('output_tokens'), int) for u in usage):
        independent = {k: sum(u[k] for u in usage) if all(isinstance(u.get(k), int) for u in usage) else None for k in keys}
        independent['total_tokens'] = independent['input_tokens'] + independent['output_tokens']
        recorded_path = directory / 'token-usage.json'
        if recorded_path.exists():
            recorded = read(recorded_path)
            if any(recorded.get(k) != v for k, v in independent.items()):
                raise ValueError('Independent usage differs: ' + str(directory))
            result['usage'] = dict(independent, status=recorded['status'])
        else:
            result['usage'] = dict(independent, status='RECONSTRUCTED_NO_SIDECAR')
    artifacts = directory / 'sdd-artifacts'
    files = [p.relative_to(artifacts).as_posix() for p in artifacts.rglob('*') if p.is_file()]
    result['planning_files'] = files
    # Presence witnesses only: no automated claim that the model understood an SDD phase.
    required = {'openspec': ('proposal.md',), 'speckit': ('spec.md', 'plan.md', 'tasks.md'),
                'cc-sdd': ('requirements.md',)}[target['method']]
    result['phase_artifact_witnesses'] = {name: [f for f in files if f.endswith('/' + name) or f == name]
                                          for name in required}
    result['phase_review'] = 'WITNESSES_PRESENT' if all(result['phase_artifact_witnesses'].values()) else 'MANUAL_REVIEW_REQUIRED'
    note = artifacts / '.detect-progress/candidate-decisions.json'
    result['decision_record_exists'] = note.exists()
    if note.exists():
        result['decision_records'] = len(read(note).get('records', {}))
    return result


def closeout(output=OUTPUT):
    output.mkdir(parents=True, exist_ok=True)
    plan, refs, targets = matched_pilot.prepared(PILOT)
    completion = read(PILOT / 'pilot-completion.json')
    if completion['states']['states'] != {'DETECT_SEALED': 27}:
        raise ValueError('Pilot incomplete')
    root, bench = first30.execution_environment(PILOT)
    from batch.testcase_metrics import compute, validate
    rows = []
    for group, ref in refs.items():
        document = compute(bench, ref['prepared_id']); validate(document, bench)
        verify_set_counts(document)
        previous = read(PILOT / 'host-comparison' / ('metrics-' + group + '.json'))
        if document['rows'] != previous['rows']:
            raise ValueError('Pilot independent evaluation changed')
        manifest = read(ref['manifest'])
        for target in manifest['targets']:
            rows.append(dict(log_audit(root, target), group=group))
    totals = {}
    for group in 'ABC':
        chosen = [r for r in rows if r['group'] == group]
        totals[group] = {'targets': len(chosen), 'usage_recorded': sum(r['usage'] is not None and r['usage']['status'] == 'RECORDED' for r in chosen),
                         **{k: sum(r['usage'][k] for r in chosen if r['usage'] and r['usage'][k] is not None)
                            for k in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens')},
                         'tool_errors': sum(len(r['tool_errors']) for r in chosen),
                         'reader_commands': sum(r['reader_commands'] for r in chosen)}
    result = {'version': 'ti26-closeout-v1', 'at': now(), 'status': 'COMPLETE_WITH_DISCLOSED_PROCESS_LIMITS',
              'sealed_targets': 27, 'evaluation_recomputed': True, 'frozen_code_and_inputs_unchanged': True,
              'groups': totals, 'rows': rows,
              'process_limitations': ['SDD artifact presence and command logs do not prove reasoning quality.',
                                      'Some planning filenames differ from conventional phase names; review witnesses remain explicit.',
                                      'Provider usage sums are not rollout counts; cached input is included, not added twice.',
                                      'Actual monetary charge and HTTP request counts are unavailable; no fabricated zero cost.'],
              'readiness': 'Continue the predeclared B/C primary comparison with identical inputs; disclose process witnesses, no prompt repair or score-based tuning.'}
    write(output / 'pilot-closeout.json', result)
    print(json.dumps({'action': 'pilot_closeout', 'targets': 27, 'usage_recorded': sum(t['usage_recorded'] for t in totals.values()),
                      'process_review_rows': sum(r['phase_review'] != 'WITNESSES_PRESENT' for r in rows)}), flush=True)
    return result


def setup(output=OUTPUT):
    if (output / 'plan.json').exists():
        raise ValueError('Already configured; do not overwrite')
    closeout(output)
    oldroot = PILOT / 'execution-root'; root = output / 'execution-root'
    if root.exists():
        raise ValueError('Execution root exists; inspect interrupted setup')
    def ignore(directory, names):
        relative = Path(directory).relative_to(oldroot).as_posix()
        ignored = {'__pycache__', '.pytest_cache'} & set(names)
        if relative == 'sdd-bench/scrapy-sdd/batch':
            ignored |= {'runs', 'baselines'} & set(names)
        if relative == 'experiment-artifacts':
            ignored |= {'matched'} & set(names)
        return ignored
    shutil.copytree(oldroot, root, ignore=ignore)
    bench = root / first30.BENCH_REL
    config = read(bench / 'batch/experiments/scrapy-30pr-testcase-v1.json')
    prs = config['prs']; remaining = [p for p in prs if p not in matched_pilot.PRS]
    if len(prs) != 30 or len(remaining) != 27:
        raise ValueError('Original 30 PR scope differs')
    schedule = [r for r in read(DESIGN / 'schedule.json') if r['group'] in GROUPS]
    if len(schedule) != TOTAL:
        raise ValueError('B/C frozen schedule differs')
    bases = sorted({r['base_sha'] for r in schedule})
    remaining_bases = {r['base_sha'] for r in schedule if not r['pilot']}
    earlier = PILOT.parent / 'p2-first30-v1/execution-root' / first30.BENCH_REL / 'batch/baselines'
    for base in bases:
        shutil.copytree(earlier / base, bench / 'batch/baselines' / base)
    configs = {}
    for group in GROUPS:
        artifacts = {}
        for base in bases:
            source = PILOT / 'materials' / group / base; checked(source)
            destination = root / 'experiment-artifacts/matched' / group / base
            shutil.copytree(source, destination)
            manifest = destination / 'manifest.json'
            if base in remaining_bases:
                artifacts[base] = {'path': manifest.relative_to(root).as_posix(), 'sha256': first30.sha(manifest)}
        updated = dict(config, experiment_id='ti27-matched-bc-' + group.lower() + '-v1', prs=remaining,
                       test_intention={'entrypoint': 'test-intentions/README.md', 'artifacts': artifacts})
        path = bench / 'batch/experiments' / ('ti27-matched-bc-' + group.lower() + '-v1.json')
        write(path, updated); configs[group] = path.relative_to(root).as_posix()
    # Controller is host-only; all Agent-visible code and prompts remain pilot bytes.
    shutil.copyfile(Path(__file__), root / 'experiment/test_intention/matched_completion.py')
    immutable = {}
    for relative, digest in read(PILOT / 'execution-lock.json')['files'].items():
        if '/batch/runs/' in relative:
            continue
        if first30.sha(root / relative) != digest:
            raise ValueError('Pilot code/runtime changed: ' + relative)
        immutable[relative] = digest
    immutable['experiment/test_intention/matched_completion.py'] = first30.sha(root / 'experiment/test_intention/matched_completion.py')
    reuse = read(PILOT / 'host-comparison/paired.json')
    reused = {group: [r for r in reuse['groups'][group]['rows']] for group in GROUPS}
    write(output / 'reused-rows.json', {'source': str(PILOT / 'host-comparison/paired.json'),
          'source_sha256': first30.sha(PILOT / 'host-comparison/paired.json'), 'groups': reused,
          'all_27_pilot_runs_preserved': True, 'A_pilot_only': 9})
    write(output / 'plan.json', {'version': 'ti27-bc-continuation-v1', 'at': now(), 'prs': prs,
          'groups': list(GROUPS), 'targets': schedule, 'new_target_count': NEW,
          'reused_target_count': REUSED, 'total_target_count': TOTAL, 'configs': configs,
          'model': 'deepseek-flash', 'effort': 'high', 'rollout_per_target': 100000,
          'timeout_seconds': 2700, 'formal_attempts': 1, 'max_parallel': 3,
          'budget_policy': 'existing_balance_no_topup', 'topup_allowed': False,
          'pilot_scores_previously_viewed': True, 'scope_revision': 'User requested B/C only and reuse all prior 27; A kept as pilot reference.',
          'not_a_fresh_holdout': True, 'new_agent_requests_limit': NEW,
          'primary': 'C-B', 'main_metric': 'SDD-equal positive-PR macro recall; failed positive tasks score zero',
          'bootstrap': {'unit': 'PR', 'samples': 10000, 'seed': 20261103, 'confidence': .95},
          'dispatch': 'One queue per SDD; original B/C relative order within each PR/SDD, no within-block overlap.'})
    write(output / 'execution-lock.json', {'files': immutable, 'plan_sha256': first30.sha(output / 'plan.json'),
          'pilot_reuse_sha256': first30.sha(output / 'reused-rows.json'), 'agent_visible_conditions': 'identical to TI26'})
    print(json.dumps({'action': 'setup', 'new': NEW, 'reused': REUSED, 'bases': len(bases)}), flush=True)


def check(output=OUTPUT):
    root = output / 'execution-root'; lock = read(output / 'execution-lock.json')
    if first30.sha(output / 'plan.json') != lock['plan_sha256'] or first30.sha(output / 'reused-rows.json') != lock['pilot_reuse_sha256']:
        raise ValueError('Plan or reused evidence changed')
    for relative, digest in lock['files'].items():
        if first30.sha(root / relative) != digest:
            raise ValueError('Execution input changed: ' + relative)
    reuse = read(output / 'reused-rows.json')
    if first30.sha(Path(reuse['source'])) != reuse['source_sha256']:
        raise ValueError('Pilot report changed')
    return read(output / 'plan.json')


def prepare(output=OUTPUT):
    plan = check(output); root, bench = first30.execution_environment(output)
    from batch.rounds import prepare_round
    references = {}
    for group, relative in plan['configs'].items():
        manifest = prepare_round(root / relative, 'ti27-bc-' + group.lower() + '-001', root=root)
        if manifest['target_count'] != NEW // 2:
            raise ValueError('Expected 81 new targets per group')
        path = bench / 'batch/runs' / manifest['prepared_id'] / 'prepared-round.json'
        references[group] = {'prepared_id': manifest['prepared_id'], 'manifest': str(path), 'sha256': first30.sha(path)}
        print(json.dumps({'action': 'prepared_group', 'group': group, 'targets': 81}), flush=True)
    write(output / 'prepared-groups.json', references)
    lock = read(output / 'execution-lock.json')
    for ref in references.values():
        directory = Path(ref['manifest']).parent
        for task in (directory / 'tasks').iterdir():
            for path in task.rglob('*'):
                parts = path.relative_to(task).parts
                if path.is_file() and parts[0] not in ('runs', 'runtime-inputs') and '__pycache__' not in parts:
                    lock['files'][path.relative_to(root).as_posix()] = first30.sha(path)
        lock['files'][Path(ref['manifest']).relative_to(root).as_posix()] = ref['sha256']
    write(output / 'execution-lock.json', lock)
    print(json.dumps({'action': 'prepared_all', 'new': NEW, 'reused': REUSED}), flush=True)


def prepared(output=OUTPUT):
    plan = check(output); root, bench = first30.execution_environment(output)
    from batch.orchestrator import validate_prepared_manifest
    refs = read(output / 'prepared-groups.json'); targets = {}
    for group, ref in refs.items():
        path = Path(ref['manifest'])
        if first30.sha(path) != ref['sha256']:
            raise ValueError('Prepared reference changed')
        config, group_targets = validate_prepared_manifest(path, bench, root)
        for t in group_targets:
            targets[(group, t['task_id'], t['method'])] = (config, t)
    if len(targets) != NEW or set(targets) != {(r['group'], r['task_id'], r['method']) for r in plan['targets'] if not r['pilot']}:
        raise ValueError('Prepared scope differs from the frozen 162')
    return plan, refs, targets


def seed_reused(journal, reused):
    with sqlite3.connect(journal.path) as db:
        db.execute('BEGIN IMMEDIATE')
        for group, rows in reused['groups'].items():
            for row in rows:
                k = group + ':' + row['task_id'] + ':' + row['method']
                detail = {'reused': True, 'source_report': reused['source'], 'source_row': row['target_key']}
                prior = db.execute('SELECT state,starts,detail FROM targets WHERE key=?', (k,)).fetchone()
                if prior:
                    if prior[0] != 'DETECT_SEALED' or prior[1] != 0 or json.loads(prior[2]) != detail:
                        raise ValueError('Reused outcome differs')
                else:
                    db.execute('INSERT INTO targets VALUES(?,?,?,?)', (k, 'DETECT_SEALED', 0, json.dumps(detail)))


def status(output=OUTPUT):
    p = output / 'ledger.sqlite3'
    rows = matched_pilot.Journal(p).rows() if p.exists() else {}
    return {'expected': TOTAL, 'new_limit': NEW, 'reused': sum(bool(r['detail'].get('reused')) for r in rows.values()),
            'states': dict(Counter(r['state'] for r in rows.values())),
            'terminal': sum(r['state'] in TERMINAL for r in rows.values()),
            'new_formal_starts': sum(r['starts'] for r in rows.values()), 'pending': TOTAL-len(rows)}


def run(output=OUTPUT):
    plan, refs, targets = prepared(output)
    auth = read(output / 'authorization.json'); acceptance = read(output / 'offline-acceptance.json')
    if auth.get('target_limit') != NEW or auth.get('budget_policy') != 'existing_balance_no_topup' or auth.get('groups') != list(GROUPS):
        raise ValueError('B/C scope and balance authorization required')
    if acceptance.get('status') != 'PASS' or acceptance['execution_lock_sha256'] != first30.sha(output / 'execution-lock.json'):
        raise ValueError('Offline acceptance absent or changed')
    root, bench = first30.execution_environment(output)
    from batch.orchestrator import Ledger, _run_duration_lock
    from batch.stages import detect_targets
    from batch.core import BatchError
    with (output / 'controller.lock').open('a') as controller, ExitStack() as stack:
        fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = matched_pilot.Journal(output / 'ledger.sqlite3')
        seed_reused(journal, read(output / 'reused-rows.json'))
        initial = journal.rows()
        if any(r['state'] == 'DETECT_RUNNING' for r in initial.values()):
            raise ValueError('Interrupted start: inspect external outcome; never automatically retry')
        ledgers = {}
        for group, ref in refs.items():
            directory = Path(ref['manifest']).parent
            stack.enter_context(_run_duration_lock(directory, ref['prepared_id']))
            ledgers[group] = Ledger(directory / 'ledger.jsonl', ref['prepared_id'], bench / 'schemas/batch-ledger-event-v1.schema.json')
        events = queue.Queue(); stopped = threading.Event()
        def worker(method):
            try:
                for row in plan['targets']:
                    k = matched_pilot.key(row)
                    if row['method'] != method or k in initial or stopped.is_set():
                        continue
                    _, target = targets[(row['group'], row['task_id'], method)]
                    acknowledge = threading.Event(); events.put(('start', row, acknowledge))
                    while not acknowledge.wait(1):
                        if stopped.is_set(): return
                    if not getattr(acknowledge, 'permitted', False): return
                    destination = target['task_manifest'].parent / 'runs' / method / 'detect/executions' / target['run_id'] / 'attempt-1'
                    try:
                        result = detect_targets(task_manifest=target['task_manifest'], method=method, run_id=target['run_id'],
                                                output=destination, bench=bench, repository_root=root,
                                                dry_run=False, localization_protocol='testcase-v1')
                        events.put(('DETECT_SEALED', row, result))
                    except Exception as exc:
                        detail = exc.as_dict() if isinstance(exc, BatchError) else {'message': str(exc)}
                        logs = '\n'.join(p.read_text(errors='replace') for p in (destination / 'agent.jsonl', destination / 'agent.stderr.log') if p.exists())
                        stop = refusal(logs + '\n' + json.dumps(detail))
                        if stop: stopped.set()
                        events.put(('FAILED', row, {'error': detail, 'stop_new_dispatch': stop}))
            finally:
                events.put(('finished', None, None))
        finished = 0
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(worker, method) for method in METHODS]
            while finished < 3:
                try: action, row, value = events.get(timeout=30)
                except queue.Empty:
                    print(json.dumps(status(output)), flush=True); continue
                if action == 'finished': finished += 1; continue
                _, target = targets[(row['group'], row['task_id'], row['method'])]
                if action == 'start':
                    if stopped.is_set():
                        detail = {'error': {'code': 'DISPATCH_STOPPED'}, 'formal_agent_started': False}
                        journal.terminal(matched_pilot.key(row), 'BLOCKED', detail)
                        ledgers[row['group']].append('detect', target, 'BLOCKED', 1, detail)
                        value.permitted = False; value.set(); continue
                    try:
                        check(output)
                        if sum(r['starts'] for r in journal.rows().values()) >= NEW:
                            raise ValueError('New-start limit reached')
                        journal.start(matched_pilot.key(row))
                        for state in ('PLANNED', 'PREFLIGHT_READY', 'DETECT_RUNNING'):
                            ledgers[row['group']].append('detect', target, state, 1, {'matched_group': row['group'], 'started': now()})
                    except BaseException:
                        stopped.set(); value.set(); raise
                    value.permitted = True; value.set()
                else:
                    try:
                        journal.terminal(matched_pilot.key(row), action, {'result': value})
                        ledgers[row['group']].append('detect', target, action, 1, value)
                        print(json.dumps({'key': matched_pilot.key(row), 'state': action, 'at': now()}), flush=True)
                    except BaseException:
                        stopped.set(); raise
            for future in futures: future.result()
        for row in plan['targets']:
            if matched_pilot.key(row) in journal.rows(): continue
            _, target = targets[(row['group'], row['task_id'], row['method'])]
            detail = {'error': {'code': 'DISPATCH_STOPPED'}, 'formal_agent_started': False}
            journal.terminal(matched_pilot.key(row), 'BLOCKED', detail)
            ledgers[row['group']].append('detect', target, 'BLOCKED', 1, detail)
        rows = journal.rows()
        if len(rows) != TOTAL or any(r['state'] not in TERMINAL for r in rows.values()):
            raise ValueError('Full terminal barrier failed')
        write(output / 'terminal.json', {'targets': rows, 'references': refs, 'at': now(),
              'ledgers': {g: first30.sha(Path(ref['manifest']).parent / 'ledger.jsonl') for g, ref in refs.items()}})


def all_task_counts(rows):
    tp = fp = fn = 0; zero = Counter(); successes = 0
    hit = all_hit = exact_positive = exact_all = positive = 0
    for row in rows:
        success = row['state'] in ('DETECT_SEALED', 'EVALUATED'); successes += success
        metric = row['testcase']
        if metric is not None:
            tp += metric['tp']; fp += metric['fp']; fn += metric['fn']
            positive += 1
            hit += success and metric['tp'] > 0
            all_hit += success and metric['fn'] == 0
            exact = success and metric['fp'] == 0 and metric['fn'] == 0
            exact_positive += exact; exact_all += exact
        elif row['status'] == 'NO_POSITIVE_GOLD':
            n = len(row['prediction']['testcases']) + len(row['prediction']['invalid'])
            zero['correct_empty' if success and n == 0 else 'false_alarm' if success else 'failed'] += 1
            if success: fp += n
            exact_all += success and n == 0
        else:
            raise ValueError('Unscorable outcome: ' + row['status'])
    return {'tasks': len(rows), 'completed': successes, 'tp': tp, 'fp': fp, 'fn': fn,
            'precision_micro': tp/(tp+fp) if tp+fp else 0., 'recall_micro': tp/(tp+fn) if tp+fn else 0.,
            'f1_micro': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0., 'no_positive': dict(zero),
            'positive_tasks': positive, 'any_hit_tasks': hit, 'all_recalled_tasks': all_hit,
            'exact_positive_tasks': exact_positive, 'exact_all_tasks': exact_all}


def verify_set_counts(document):
    """Independent set arithmetic against host labels; only after terminal barriers."""
    for row in document['rows']:
        gold = set(document['tasks'][row['task_id']]['labels']['testcases'])
        predicted = set(row['prediction']['testcases'])
        invalid = set(row['prediction']['invalid'])
        if not gold:
            if row['status'] != 'NO_POSITIVE_GOLD': raise ValueError('Zero-gold status differs')
            continue
        if row['state'] in ('FAILED', 'BLOCKED'):
            predicted = set(); invalid = set()
        expected = {'tp': len(predicted & gold), 'fp': len(predicted - gold) + len(invalid),
                    'fn': len(gold - predicted), 'gold_count': len(gold),
                    'predicted_count': len(predicted) + len(invalid)}
        if row['testcase'] is None or any(row['testcase'][k] != v for k, v in expected.items()):
            raise ValueError('Independent prediction/label set counts differ')
    return len(document['rows'])


def usage_summary(rows):
    fields = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens')
    result = {'targets': len(rows), 'recorded': sum(bool(r['usage']) and r['usage']['status'] == 'RECORDED' for r in rows),
              'missing': sum(r['usage'] is None for r in rows),
              'partial_or_reconstructed': sum(bool(r['usage']) and r['usage']['status'] != 'RECORDED' for r in rows)}
    result['known_sums'] = {f: sum(r['usage'][f] for r in rows if r['usage'] and r['usage'].get(f) is not None) for f in fields}
    result['unknown_target_counts'] = {f: sum(r['usage'] is None or r['usage'].get(f) is None for r in rows) for f in fields}
    result['actual_currency'] = None
    return result


def paired_bootstrap(groups, samples=10000, seed=20261103):
    maps = {g: {(r['task_id'], r['method']): r for r in d['rows']} for g, d in groups.items()}
    ids = sorted({task for task, method in maps['B'] if maps['B'][(task, method)]['testcase'] is not None})
    differences = {task: statistics.mean(maps['C'][(task, m)]['testcase']['recall'] - maps['B'][(task, m)]['testcase']['recall'] for m in METHODS) for task in ids}
    rng = random.Random(seed)
    values = sorted(statistics.mean(differences[rng.choice(ids)] for _ in ids) for _ in range(samples))
    def quantile(q):
        pos = (len(values)-1)*q; lo = int(pos); hi = min(lo+1, len(values)-1)
        return values[lo] + (values[hi]-values[lo])*(pos-lo)
    return {'unit': 'PR', 'positive_prs': len(ids), 'samples': samples, 'seed': seed,
            'primary_delta': statistics.mean(differences.values()), 'interval_95': [quantile(.025), quantile(.975)],
            'per_pr_recall_delta': differences, 'not_model_repeat_uncertainty': True}


def compare(output=OUTPUT):
    plan, refs, targets = prepared(output); terminal = read(output / 'terminal.json')
    if len(terminal['targets']) != TOTAL or any(r['state'] not in TERMINAL for r in terminal['targets'].values()):
        raise ValueError('All 180 outcomes required before new scoring')
    root, bench = first30.execution_environment(output)
    from batch.testcase_metrics import compute, validate, summarize
    from .compact_pilot import aggregate
    reused = read(output / 'reused-rows.json'); groups = {}
    ids = {(r['task_id'], r['method']) for r in plan['targets']}
    for group, ref in refs.items():
        if first30.sha(Path(ref['manifest']).parent / 'ledger.jsonl') != terminal['ledgers'][group]:
            raise ValueError('Terminal native ledger changed')
        document = compute(bench, ref['prepared_id']); validate(document, bench)
        verify_set_counts(document)
        write(output / 'host-comparison' / ('metrics-' + group + '.json'), document)
        document = dict(document, rows=document['rows'] + reused['groups'][group])
        groups[group] = aggregate(document, ids, summarize)
        groups[group]['all_task_micro'] = all_task_counts(groups[group]['rows'])
        groups[group]['file_level'] = {name: summarize(groups[group]['rows'], name) for name in ('scoped_file', 'legacy_file')}
        for method in groups[group]['methods']:
            chosen = [r for r in groups[group]['rows'] if r['method'] == method['method']]
            method['all_task_micro'] = all_task_counts(chosen)
    b = {(r['task_id'], r['method']): r for r in groups['B']['rows']}
    for row in groups['C']['rows']:
        peer = b[(row['task_id'], row['method'])]
        if (row['index_sha256'], row['labels_sha256']) != (peer['index_sha256'], peer['labels_sha256']):
            raise ValueError('Paired labels or source identities differ')
    stats = paired_bootstrap(groups, **{k: plan['bootstrap'][k] for k in ('samples', 'seed')})
    audits = []
    for row in plan['targets']:
        if row['pilot']: continue
        _, target = targets[(row['group'], row['task_id'], row['method'])]
        audits.append(dict(log_audit(root, target), group=row['group']))
    write(output / 'runtime-audit.json', {'rows': audits, 'at': now(), 'usage_missing_is_unknown': True})
    pilot_audits = read(output / 'pilot-closeout.json')['rows']
    usage = {group: {'new': usage_summary([r for r in audits if r['group'] == group]),
                     'reused': usage_summary([r for r in pilot_audits if r['group'] == group]),
                     'combined': usage_summary([r for r in audits + pilot_audits if r['group'] == group])} for group in GROUPS}
    peer_maps = {g: {(r['task_id'], r['method']): r for r in d['rows']} for g, d in groups.items()}
    differences = []
    common_success = {g: [] for g in GROUPS}
    for task, method in sorted(peer_maps['B']):
        left, right = (peer_maps[g][(task, method)] for g in GROUPS)
        differences.append({'task_id': task, 'method': method, 'B_state': left['state'], 'C_state': right['state'],
                            'B': left['testcase'], 'C': right['testcase'],
                            'delta': {name: right['testcase'][name]-left['testcase'][name] for name in ('tp', 'fp', 'fn', 'precision', 'recall', 'f1')}
                            if left['testcase'] is not None and right['testcase'] is not None else None})
        if all(r['state'] in ('DETECT_SEALED', 'EVALUATED') for r in (left, right)):
            common_success['B'].append(left); common_success['C'].append(right)
    write(output / 'host-comparison/per-task-differences.json', differences)
    main_f1 = {g: statistics.mean(m['testcase']['f1_macro'] for m in groups[g]['methods']) for g in GROUPS}
    completion_delta = (groups['C']['all_task_micro']['completed']-groups['B']['all_task_micro']['completed'])/90
    if stats['primary_delta'] <= 0:
        conclusion = '本开发协议下未观察到主指标召回收益。'
    elif main_f1['C'] < main_f1['B'] or completion_delta < 0:
        conclusion = '召回上涨伴随F1或完成率下降，存在收益与代价。'
    elif stats['interval_95'][0] > 0:
        conclusion = '按事前判据，支持语义增强在本开发协议中有收益；不外推泛化。'
    else:
        conclusion = '观察到召回上涨，但配对区间包含零，稳定收益证据不足。'
    result = {'version': 'ti28-bc-report-v1', 'at': now(), 'paired_input_check': 'PASS', 'groups': groups,
              'primary_analysis': stats, 'scope_revision': plan['scope_revision'], 'reused': REUSED,
              'independent_set_count_verification': 'PASS: new rows independently recomputed against label sets; pilot rows checked at closeout',
              'new_formal_starts': status(output)['new_formal_starts'], 'zero_positive_policy': 'Separate correct empty, false alarm, failed; supplementary all-task micro includes false alarms.',
              'development_only': True, 'A_reference': str(PILOT / 'host-comparison/paired.json'),
              'conclusion': conclusion, 'macro_f1': main_f1, 'completion_rate_delta': completion_delta,
              'common_success_auxiliary_only': {g: all_task_counts(rows) for g, rows in common_success.items()},
              'usage': usage, 'generation_reference': str(PILOT.parent / 'stage-a-codex-20261104-v1/publication-v1'),
              'cost': {'actual_currency': None, 'http_requests': None, 'reason': 'Provider billing/HTTP traces unavailable; CLI usage reported separately.',
                       'new_generation_requests': 0}}
    write(output / 'host-comparison/paired.json', result)
    lines = ['# 阶段 C：B/C 匹配比较完成报告', '', '范围：原30个开发PR × 三种SDD × B/C两组，共180项；复用小批18项，最多新增162项。', '',
             '小批A组9项保留为历史参照，不扩展、不冒充完整30PR对照。小批分数在扩展前已查看，输入未据此调优，范围修订已披露。', '',
             '| 指标（含无正例任务的补充Micro口径） | B：静态 | C：静态＋语义 |', '| --- | ---: | ---: |']
    for label, field in [('完成数', 'completed'), ('TP', 'tp'), ('FP', 'fp'), ('FN', 'fn'), ('精确率', 'precision_micro'), ('召回率', 'recall_micro'), ('F1', 'f1_micro')]:
        values = [groups[g]['all_task_micro'][field] for g in GROUPS]
        display = [f'{v:.2%}' if field.endswith('micro') else str(v) for v in values]
        lines.append(f'| {label} | {display[0]} | {display[1]} |')
    lines += ['', '## 事前主比较', '', f"C−B的三种SDD等权Macro Recall差值：{stats['primary_delta']:.2%}；按PR配对重采样95%区间：{stats['interval_95'][0]:.2%}～{stats['interval_95'][1]:.2%}。", '',
              conclusion, '',
              '每项一次尝试；该区间不代表模型重复运行波动。全部任务和失败均保留，不能以共同成功子集替代主报告。', '',
              '## 各 SDD 的有正例 Macro 指标', '', '| SDD | B P | C P | B R | C R | B F1 | C F1 |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for method in METHODS:
        metrics = {g: next(m['testcase'] for m in groups[g]['methods'] if m['method'] == method) for g in GROUPS}
        values = [metrics[g][name + '_macro'] for name in ('precision', 'recall', 'f1') for g in GROUPS]
        lines.append('| ' + method + ' | ' + ' | '.join(f'{v:.2%}' for v in values) + ' |')
    lines += ['', '## 运行用量（包含复用项，缓存输入已包含在输入中）', '',
              '| 组 | 已知输入 | 其中缓存 | 已知输出 | 已知合计 | 缺失总量记录 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for group in GROUPS:
        total = usage[group]['combined']; counts = total['known_sums']
        lines.append(f"| {group} | {counts['input_tokens']} | {counts['cached_input_tokens']} | {counts['output_tokens']} | {counts['total_tokens']} | {total['unknown_target_counts']['total_tokens']} |")
    lines += ['',
              '## 完整数据与成本边界', '', '逐PR、逐SDD指标、无正例分类及来源见 host-comparison/paired.json；运行日志检查与数值用量见 runtime-audit.json，已复用项用量见 pilot-closeout.json。', '',
              'provider输入/输出及缓存量不等于rollout，缓存输入已包含在输入中。未知货币费用和HTTP请求数保持未知；生成与定位分开记账。未充值，没有新增语义生成。', '',
              '本轮属于开发结果，不支持未参与调优任务上的泛化结论。']
    (output / 'RESULTS.md').write_text('\n'.join(lines) + '\n')
    write(output / 'completion.json', {'status': 'COMPLETE', 'at': now(), 'states': status(output),
          'paired_input_check': 'PASS', 'report': str(output / 'RESULTS.md'),
          'unknown_actual_currency': True, 'new_generation_requests': 0})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('closeout', 'setup', 'prepare', 'check', 'status', 'run', 'compare', 'workflow'))
    parser.add_argument('--output', type=Path, default=OUTPUT); args = parser.parse_args()
    if args.action == 'workflow': run(args.output); compare(args.output)
    elif args.action == 'status': print(json.dumps(status(args.output)))
    else: globals()[args.action](args.output)


if __name__ == '__main__':
    main()
