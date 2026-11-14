"""Continue the authorized first30 workflow after its current generation process."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .first30 import DEFAULT_OUTPUT, SOURCE_ROOT
from .static import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--generation-pid', type=int, required=True)
    args = parser.parse_args()
    output = DEFAULT_OUTPUT
    status_path = output / 'execution-status.json'
    step = 'WAITING_FOR_GENERATION'
    write(status_path, {'stage': step, 'state': 'RUNNING', 'generation_pid': args.generation_pid})
    try:
        process = Path('/proc') / str(args.generation_pid)
        while process.exists():
            try:
                if process.joinpath('stat').read_text().split()[2] == 'Z':
                    break
                command = process.joinpath('cmdline').read_bytes()
            except FileNotFoundError:
                break
            if b'experiment.test_intention.pipeline\x00generate' not in command:
                break
            time.sleep(5)
        if not (output / 'generation-summary.json').is_file():
            raise RuntimeError('Generation exited without a final summary')
        scope = json.loads((output / 'scope.json').read_text())
        if any(not (output / 'representations' / base / 'manifest.json').is_file() for base in scope['base_shas']):
            raise RuntimeError('Generation did not finish publishing all bases')
        for module, action in (('pipeline', 'publish'), ('first30', 'mirror'),
                               ('first30', 'prepare'), ('first30', 'run'), ('first30', 'compare')):
            step = action.upper()
            write(status_path, {'stage': step, 'state': 'RUNNING'})
            print(json.dumps({'stage': step, 'state': 'STARTED'}), flush=True)
            subprocess.run([sys.executable, '-m', 'experiment.test_intention.' + module, action], cwd=SOURCE_ROOT, check=True)
            print(json.dumps({'stage': step, 'state': 'COMPLETED'}), flush=True)
        source = output / 'host-comparison/report.md'
        destination = SOURCE_ROOT / 'experiment/TEST_INTENTION_FIRST30_RESULTS.md'
        destination.write_text(source.read_text() + '\n完整宿主机产物：`' + str(output / 'host-comparison') + '`。\n')
        write(status_path, {'stage': 'COMPLETE', 'state': 'COMPLETED', 'report': str(destination)})
    except BaseException as exc:
        write(status_path, {'stage': step, 'state': 'FAILED', 'error_type': type(exc).__name__, 'error': str(exc)})
        raise


if __name__ == '__main__':
    main()
