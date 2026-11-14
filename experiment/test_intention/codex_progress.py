"""Read-only subscription generation progress. Never launches/resumes a model."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import sqlite3

from .recovery import now


def report(plan_directory,execution):
    plan=json.loads((plan_directory/'plan.json').read_text())
    with sqlite3.connect((execution/'ledger.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        states=dict(db.execute('SELECT key,state FROM packets'))
        requests=list(db.execute('SELECT id,state FROM requests'))
    totals=Counter(states.values());bases=defaultdict(Counter);usage=Counter();missing=0
    for row in plan['rows']:
        state=states.get(row['new_key'],'PENDING')
        for base in row['base_shas']:
            bases[base]['planned_records']+=len(row['tests'])
            bases[base][state]+=len(row['tests'])
    for request_id,state in requests:
        if state=='REQUEST_STARTED':continue
        path=execution/'responses'/(request_id+'.json')
        value=json.loads(path.read_text()).get('usage') if path.exists() else None
        if not value:missing+=1;continue
        for key,value in value.items():
            if isinstance(value,int):usage[key]+=value
    return dict(captured_at=now(),backend='chatgpt-subscription',model=plan['options']['model'],
                packet_states=dict(totals),planned_packets=len(plan['rows']),
                restored_versioned_records=sum(c['GENERATED'] for c in bases.values()),
                pending_versioned_records=sum(c['PENDING'] for c in bases.values()),
                planned_restoration_records=plan['expected_restored_versioned_records'],
                known_cli_token_usage=dict(usage),completed_invocations_missing_usage=missing,
                in_flight_invocations=sum(state=='REQUEST_STARTED' for _,state in requests),
                cli_invocations=len(requests),prior_unavailable_model_invocations=plan.get('prior_subscription_attempts',{}).get('count',0),
                direct_api_calls=0,extra_credit_purchases=0,per_base={b:dict(c) for b,c in sorted(bases.items())},
                note='Generated means structure/reference-validated, not finished semantic quality review.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--execution',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(report(args.plan,args.execution),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
