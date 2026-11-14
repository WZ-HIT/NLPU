"""Durable preparation -> no-model acceptance -> authorized B/C run -> report."""
from datetime import datetime
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from . import matched_completion as full


def same_process(pid, start_ticks):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()
        return fields[0] != 'Z' and fields[19] == str(start_ticks)
    except (OSError, IndexError):
        return False


def progress(output, stage, **extra):
    value = {'at': full.now(), 'stage': stage, 'scope': 'B/C only, reuse 18 and at most 162 new formal starts', **extra}
    full.write(output / 'supervisor-status.json', value)
    print(json.dumps(value, ensure_ascii=False), flush=True)


def run_module(output, module, args=(), log_name=None):
    root = output / 'execution-root'
    command = [sys.executable, '-B', '-u', '-m', module, *args]
    if log_name is None:
        result = subprocess.run(command, cwd=root)
        if result.returncode: raise RuntimeError(f'{module} exited {result.returncode}')
        return
    log_path = output / log_name
    if log_path.exists(): raise ValueError('Refusing to overwrite prior workflow log')
    with log_path.open('xb') as log:
        process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    fields = Path(f'/proc/{process.pid}/stat').read_text().split(') ', 1)[1].split()
    full.write(output / 'workflow-process.json', {'pid': process.pid, 'start_ticks': fields[19],
               'command': command, 'cwd': str(root), 'at': full.now(), 'log': str(log_path)})
    while process.poll() is None:
        progress(output, 'TI27_RUNNING', **full.status(output))
        time.sleep(30)
    if process.returncode: raise RuntimeError(f'B/C workflow exited {process.returncode}; inspect evidence, no automatic model retry')


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else full.OUTPUT
    with (output / 'supervisor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            prep = full.read(output / 'preparation-process.json')
            while same_process(prep['pid'], prep['start_ticks']):
                runs = output / 'execution-root/sdd-bench/scrapy-sdd/batch/runs'
                groups = [{'round': p.name, 'tasks': len(list((p / 'tasks').glob('*'))),
                           'preflight_complete': len(list((p / 'tasks').glob('*/preflight-summary.json'))),
                           'frozen': (p / 'prepared-round.json').exists()} for p in runs.glob('round-*')]
                progress(output, 'TI27_PREPARING_NO_MODEL_CALLS', groups=groups)
                time.sleep(30)
            if not (output / 'prepared-groups.json').exists():
                # Repeating interrupted read-only preparation cannot resend a formal model target.
                progress(output, 'RESUMING_OFFLINE_PREPARATION_NO_MODEL_CALLS')
                run_module(output, 'experiment.test_intention.matched_completion', ['prepare', '--output', str(output)])
            full.prepared(output)
            progress(output, 'TI27_OFFLINE_ACCEPTANCE_NO_MODEL_CALLS')
            if not (output / 'offline-acceptance.json').exists():
                run_module(output, 'experiment.test_intention.matched_completion_acceptance', [str(output)])
            acceptance = full.read(output / 'offline-acceptance.json')
            if acceptance['status'] != 'PASS' or acceptance['execution_lock_sha256'] != full.first30.sha(output / 'execution-lock.json'):
                raise ValueError('Offline acceptance differs; no model may start')
            if (output / 'workflow-process.json').exists() and not (output / 'completion.json').exists():
                raise ValueError('Prior formal workflow found; inspect outcome before any continuation')
            if not (output / 'completion.json').exists():
                progress(output, 'TI27_STARTING_AUTHORIZED_BC_ONLY')
                run_module(output, 'experiment.test_intention.matched_completion', ['workflow', '--output', str(output)], 'workflow.log')
            complete = full.read(output / 'completion.json')
            if complete['status'] != 'COMPLETE': raise ValueError('Completion report not final')
            project = Path('/home/wangzuohit/NLPU/experiment')
            report = project / 'TEST_INTENTION_STAGE_C_RESULTS.md'
            if report.exists(): raise ValueError('Result document exists; preserve it and inspect before replacement')
            shutil.copyfile(output / 'RESULTS.md', report)
            states = full.status(output)
            progress(output, 'C_FINISHED_WITH_BLOCKED_TARGETS' if states['states'].get('BLOCKED') else 'C_COMPLETE',
                     result_document=str(report), **states)
        except BaseException as exc:
            progress(output, 'STOPPED_INSPECT_REQUIRED', error_type=type(exc).__name__, error=str(exc),
                     automatic_model_retries=0)
            raise


if __name__ == '__main__':
    main()
