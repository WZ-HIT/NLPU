"""Host-side export of public TI-21 observations. Does not read labels."""
import argparse
import json
from pathlib import Path


def export(planning, prediction=None, run_state='UNKNOWN'):
    path=Path(planning)/'.detect-progress/candidate-decisions.json'
    final=set()
    if prediction is not None:
        for candidate in prediction.get('candidates',[]):
            final.update(candidate['path']+'::'+s for s in candidate['symbols'])
    if not path.is_file():
        return {'record_status':'MISSING','coverage':'UNKNOWN','rows':[],
                'run_state':run_state,'note':'Missing records are not evidence of missing investigation'}
    state=json.loads(path.read_text())
    if state.get('version')!='candidate-decisions-v1':raise ValueError('Unsupported decisions version')
    rows=[]
    for identity,entry in sorted(state['records'].items()):
        record=entry['record']
        stage=('SELECTED_RUN_FAILED' if record['state']=='selected' and run_state in ('FAILED','BLOCKED') else
               'SELECTED_FINAL' if identity in final else
               'SELECTED_NOT_FINAL' if record['state']=='selected' and prediction is not None else
               'SELECTED_OUTPUT_UNKNOWN' if record['state']=='selected' else
               'EXPANDED_EXCLUDED_REPORTED' if record['state']=='excluded' and record['exposure']['stage']=='source_expanded' else
               'EXCLUDED_REPORTED' if record['state']=='excluded' else 'PENDING')
        rows.append(dict(record,diagnostic_stage=stage,revision=entry['revision'],history=entry.get('history',[]),
                         exposure_basis='Agent-reported, not independently proven attention',
                         selected_final=identity in final if prediction is not None else None))
    return {'record_status':'PRESENT','coverage':'investigated candidates with saved notes only',
            'run_state':run_state,'rows':rows,'source':str(path)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--planning',type=Path,required=True)
    p.add_argument('--prediction',type=Path)
    p.add_argument('--run-state',default='UNKNOWN')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Refusing overwrite')
    result=export(args.planning,json.loads(args.prediction.read_text()) if args.prediction else None,args.run_state)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
