"""Derived live status for D; never starts, retries, or modifies model targets."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import time


def load(path,default=None):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default


def snapshot(output):
    process=load(output/'workflow-process.json',{})
    active=False
    try:
        fields=Path(f"/proc/{process['pid']}/stat").read_text().split(') ',1)[1].split()
        active=fields[0]!='Z' and fields[19]==str(process['start_ticks'])
    except (KeyError,OSError,IndexError):pass
    rows=[]
    path=output/'ledger.sqlite3'
    if path.is_file():
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
            rows=db.execute('SELECT state,starts FROM targets').fetchall()
    states=Counter(s for s,n in rows)
    runs=output/'execution-root/sdd-bench/scrapy-sdd/batch/runs'
    prep=[{'prepared_id':p.name,'tasks_created':len(list((p/'tasks').glob('*'))),
           'preflight_completed':len(list((p/'tasks').glob('*/preflight-summary.json'))),
           'frozen':(p/'prepared-round.json').is_file()} for p in runs.glob('round-*')]
    stage=load(output/'execution-status.json',{})
    return {'at':datetime.now(timezone.utc).isoformat(),'group':'D','expected':90,
            'workflow_alive':active,'workflow':process,'stage':stage.get('stage'),
            'states':dict(states),'formal_starts':sum(n for s,n in rows),
            'terminal':sum(n for s,n in states.items() if s in {'DETECT_SEALED','FAILED','BLOCKED'}),
            'unregistered':90-len(rows),'preparation':prep,
            'completion':load(output/'completion.json')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--watch',action='store_true')
    args=parser.parse_args();output=args.output.resolve()
    while True:
        state=snapshot(output)
        if not args.watch:
            print(json.dumps(state,ensure_ascii=False));return
        target=output/'live-status.json';temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');temporary.replace(target)
        if state['completion'] is not None or not state['workflow_alive']:return
        time.sleep(30)


if __name__=='__main__':main()
