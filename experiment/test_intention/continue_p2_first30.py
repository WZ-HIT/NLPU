"""Durably wait for no-model preparation, then run frozen P2 Detect+evaluation."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

from .first30 import sha
from .p2_first30 import OUTPUT, now
from .static import write


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-pid',type=int,required=True)
    parser.add_argument('--prepare-start',required=True);args=parser.parse_args()
    stage='WAITING_FOR_PREPARE'
    try:
        write(OUTPUT/'automation-status.json',{'stage':stage,'state':'RUNNING','pid':os.getpid(),'updated_utc':now()})
        process=Path('/proc')/str(args.prepare_pid)
        while process.exists():
            try:
                stat=(process/'stat').read_text().split()
                if stat[21]!=args.prepare_start or stat[2]=='Z':
                    break
                command=(process/'cmdline').read_bytes()
            except FileNotFoundError:
                break
            if b'experiment.test_intention.p2_first30\x00prepare' not in command:
                break
            time.sleep(5)
        state=json.loads((OUTPUT/'execution-status.json').read_text())
        if state.get('stage')!='prepare' or state.get('state')!='COMPLETED':
            raise RuntimeError('Preparation did not complete; model workflow not started')
        reference=json.loads((OUTPUT/'prepared-reference.json').read_text())
        if (Path(reference['manifest']).parent/'ledger.jsonl').stat().st_size:
            raise RuntimeError('Existing formal attempts prevent controller revision')
        # Host-only terminal checks were strengthened before any formal model attempt.
        candidate=OUTPUT/'controller-candidate/p2_first30.py'
        metadata=json.loads((candidate.parent/'metadata.json').read_text())
        if sha(candidate)!=metadata['sha256']:
            raise RuntimeError('Candidate controller changed')
        root=OUTPUT/'execution-root';lock=json.loads((OUTPUT/'controller-lock.json').read_text())
        write(OUTPUT/'controller-lock.before-host-checks.json',lock)
        shutil.copyfile(candidate,root/'experiment/test_intention/p2_first30.py')
        paths=list((root/'experiment').rglob('*.py'))
        paths+=list((root/'sdd-bench/scrapy-sdd/batch').rglob('*.py'))
        paths+=list((root/'sdd-bench/scrapy-sdd/schemas').glob('*.json'))
        lock.update(files={p.relative_to(root).as_posix():sha(p) for p in sorted(paths)},
                    revision=2,revision_reason='pre-model full terminal-barrier checks and scoring-code pinning',updated_utc=now())
        write(OUTPUT/'controller-lock.json',lock)
        write(OUTPUT/'automation-status.json',{'stage':'MODEL_WORKFLOW','state':'RUNNING','pid':os.getpid(),'updated_utc':now()})
        os.chdir(root)
        os.execv(sys.executable,[sys.executable,'-B','-m','experiment.test_intention.p2_first30','workflow'])
    except BaseException as exc:
        write(OUTPUT/'automation-status.json',{'stage':stage,'state':'FAILED','error':type(exc).__name__+': '+str(exc),'updated_utc':now()})
        raise


if __name__=='__main__':
    main()
