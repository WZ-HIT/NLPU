"""Host-only conditional TI-10 audit using new inheritance evidence, not ranking rules."""
from collections import defaultdict
import json

from .p2_gate import OUTPUT, P1
from .p1_offline import RUN
from . import maintenance_view as view
from .search_view import sha


def main():
    tasks=json.loads((OUTPUT/'queries.json').read_text())['tasks']
    labels=json.loads((RUN/'host-comparison/metrics.json').read_text())['tasks']
    rows=[];hubs=set();scanned=0
    for task in tasks:
        prediction=json.loads((P1/'rankings'/task['task_id']/'R.json').read_text())
        seeds=prediction['visible_ids'][:4];pool=set(prediction['ranked_ids'])
        gold=set(labels[task['task_id']]['labels']['testcases'])
        root=OUTPUT/'representations'/task['base_sha']
        memberships=defaultdict(dict)
        with view.connect(root) as db:
            for identity,raw in db.execute("SELECT m.test_id,f.record FROM members m JOIN facts f ON m.fact_id=f.id WHERE m.category='inheritance' ORDER BY m.test_id,m.ordinal"):
                fact=json.loads(raw)
                if len(fact['targets'])!=1 or 'inheritance cycle candidate' in fact['uncertainty']:
                    continue
                via=fact['targets'][0]
                memberships[via].setdefault(identity,fact)
        for via,members in memberships.items():
            degree=len(members)
            if degree>12:
                hubs.add((task['base_sha'],via))
            if not 2<=degree<=12:
                continue
            scanned+=1
            for seed in seeds:
                if seed not in members:
                    continue
                for candidate,fact in members.items():
                    if candidate in prediction['visible_ids']:
                        continue
                    rows.append({'task_id':task['task_id'],'seed':seed,'candidate':candidate,'via':via,'degree':degree,
                        'seed_fact':members[seed],'candidate_fact':fact,
                        'omission':'page_only' if candidate in pool else 'not_in_match_pool',
                        'gold_after_seal':candidate in gold,
                        'basis':'explicit base-expression candidate; shared ancestry is not proof of joint update'})
    outside=[r for r in rows if r['gold_after_seal'] and r['omission']=='not_in_match_pool']
    page=[r for r in rows if r['gold_after_seal'] and r['omission']=='page_only']
    result={'scope':'30 development PR; first 4 fixed P1 R seeds; new inheritance; degree 2..12',
        'low_degree_groups_scanned':scanned,'high_degree_groups_excluded':len(hubs),
        'outside_pool_gold_tasks':sorted({r['task_id'] for r in outside}),
        'page_only_gold_tasks':sorted({r['task_id'] for r in page}),'rows':rows,
        'candidate_gate_pass':bool(outside),'manual_source_review_required':bool(outside),
        'p1_seal_sha256':sha(P1/'rankings-seal.json')}
    destination=OUTPUT/'inheritance-relation-audit.json'
    if destination.exists():
        raise ValueError('Relation audit already exists')
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
