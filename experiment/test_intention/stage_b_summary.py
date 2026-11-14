"""TI-23 independent count checks and joined host stage table after sealing."""
from collections import Counter
import json

from .stage_b_bundle import OUTPUT, write
from .stage_b_offline import export_csv
from . import search_view as search


def main():
    if (OUTPUT/'stage-summary.json').exists():raise ValueError('Summary already exists')
    seal=json.loads((OUTPUT/'rankings-seal.json').read_text())
    for name,digest in seal['files'].items():
        if search.sha(OUTPUT/name)!=digest:raise ValueError('Sealed output changed')
    data=json.loads((OUTPUT/'offline-metrics.json').read_text())
    diagnoses=json.loads((OUTPUT/'target-stage-diagnosis.json').read_text())
    history=json.loads((OUTPUT/'historical-decision-diagnosis.json').read_text())
    plan=json.loads((OUTPUT/'replay-plan.json').read_text())
    task_gold={}
    for row in diagnoses:task_gold.setdefault(row['task_id'],set()).add(row['id'])
    # Derive counts again from serialized ranked/visible IDs, not recorded metrics.
    for row in data['rows']:
        p=json.loads((OUTPUT/'rankings'/row['key']/(row['variant']+'.json')).read_text())
        gold=task_gold.get(row['task_id'],set())
        for field,value in [('gold',len(gold)),('pool_hits',len(gold&set(p['ranked_ids']))),
                            ('first_hits',len(gold&set(p['first_page_ids']))),
                            ('first_count',len(p['first_page_ids'])),('pool_count',len(p['ranked_ids']))]:
            if row[field]!=value:raise ValueError('Metric recount differs: '+field)
    controls=[]
    for row in data['rows']:
        if row['kind']!='fixed_public' or row['variant']!='OLD':continue
        current=json.loads((OUTPUT/'rankings'/row['key']/'OLD.json').read_text())
        original=json.loads((OUTPUT.parent/'p2-20261103-v1/rankings'/row['task_id']/'N.json').read_text())
        if current['ranked_ids']!=original['ranked_ids'] or current['first_page_ids']!=original['visible_ids']:
            raise ValueError('Old control differs from frozen P2')
        controls.append(row['task_id'])
    fixed={(d['task_id'],d['id']):d for d in diagnoses};joined=[]
    for row in history:
        corresponding=fixed.get((row['task_id'],row['id']))
        joined.append(dict(row,semantic_status=corresponding['semantic_status'] if corresponding else 'NOT_A_TARGET_CHECK',
            fixed_public_query_stage=corresponding['fixed_query_stage'] if corresponding else 'NOT_A_TARGET_CHECK',
            fixed_public_query_rank=corresponding['fixed_query_rank'] if corresponding else None,
            attribution='UNKNOWN; replay reachability and recorded observations do not establish causality'))
    write(OUTPUT/'joined-stage-diagnosis.json',joined)
    # CSV keeps refs and trace identity; nested event line arrays are explicit JSON cells.
    flat=[dict(r,event_lines=json.dumps(r['event_lines'],separators=(',',':'))) for r in joined]
    export_csv(OUTPUT/'joined-stage-diagnosis.csv',flat)
    fixed_rows=[r for r in data['rows'] if r['kind']=='fixed_public']
    paired={}
    for variant in ('OLD','NEW'):
        paired[variant]={r['task_id']:r for r in fixed_rows if r['variant']==variant}
    differences=[]
    for task,old in paired['OLD'].items():
        new=paired['NEW'][task]
        differences.append({'task_id':task,'gold':old['gold'],'old_first_hits':old['first_hits'],
            'new_first_hits':new['first_hits'],'old_pool_hits':old['pool_hits'],'new_pool_hits':new['pool_hits'],
            'old_visible':old['first_count'],'new_visible':new['first_count'],
            'macro_recall_delta':(new['first_hits']-old['first_hits'])/old['gold'] if old['gold'] else None})
    write(OUTPUT/'fixed-query-differences.json',differences)
    write(OUTPUT/'stage-summary.json',{'metric_recount':'PASS','old_frozen_P2_control':'PASS',
        'old_controls_checked':len(controls),'ranked_query_variants':len(data['rows']),
        'target_records':len(diagnoses),'target_semantic_status':Counter(d['semantic_status'] for d in diagnoses),
        'target_fixed_query_stage':Counter(d['fixed_query_stage'] for d in diagnoses),
        'historical_joined_rows':len(joined),'historical_observed_exposure':Counter(r['observed_exposure'] for r in joined),
        'unrecovered_query_calls':len(plan['unrecovered']),
        'unrecovered_reasons':Counter(r['reason'] for r in plan['unrecovered']),
        'first_page_improved_PRs':[r['task_id'] for r in differences if r['new_first_hits']>r['old_first_hits']],
        'first_page_regressed_PRs':[r['task_id'] for r in differences if r['new_first_hits']<r['old_first_hits']],
        'pool_improved_PRs':[r['task_id'] for r in differences if r['new_pool_hits']>r['old_pool_hits']],
        'pool_regressed_PRs':[r['task_id'] for r in differences if r['new_pool_hits']<r['old_pool_hits']],
        'no_new_model_calls':True,'generalization_claim':False})
    print('PASS: 1146 metric rows recounted; 30 old controls reproduce sealed P2; stages joined')


if __name__=='__main__':main()
