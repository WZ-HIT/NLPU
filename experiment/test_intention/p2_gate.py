"""Host-only P2 launch audit; labels never feed public facts or query generation."""
from collections import defaultdict
import json
from pathlib import Path
import sqlite3

from .p1_offline import OUTPUT as P1, RUN
from .search_view import sha

OUTPUT = P1.parent/'p2-20261103-v1'
BASELINES = Path(__file__).resolve().parents[2]/'sdd-bench/scrapy-sdd/batch/baselines'
STRONG = {'uses_fixture', 'initialization-definition'}


def main():
    tasks = json.loads((P1/'queries.json').read_text())['tasks']
    labels = json.loads((RUN/'host-comparison/metrics.json').read_text())['tasks']
    rows = []
    for task in tasks:
        prediction = json.loads((P1/'rankings'/task['task_id']/'R.json').read_text())
        seeds, pool = prediction['visible_ids'][:4], set(prediction['ranked_ids'])
        gold = set(labels[task['task_id']]['labels']['testcases'])
        root = P1/'representations'/task['base_sha']
        with sqlite3.connect((root/'.evidence.sqlite3').as_uri()+'?mode=ro&immutable=1', uri=True) as db:
            tests = {i for (i,) in db.execute('SELECT id FROM tests')}
            memberships = defaultdict(list)
            for source, target, relation in db.execute('SELECT source,target,relation FROM edges WHERE depth=1 ORDER BY source,target,relation'):
                if source in tests:
                    memberships[target].append((source, relation))
            contexts = {i: json.loads(m) for i, m in db.execute('SELECT id,metadata FROM contexts')}
            for via, members in memberships.items():
                degree = len({i for i, _ in members})
                if not 2 <= degree <= 12:
                    continue
                for seed, seed_relation in members:
                    if seed not in seeds:
                        continue
                    for candidate, relation in members:
                        if candidate in prediction['visible_ids'] or candidate == seed:
                            continue
                        strong = seed_relation == relation and relation in STRONG
                        rows.append({'task_id': task['task_id'], 'base_sha': task['base_sha'],
                            'seed': seed, 'candidate': candidate, 'via': via,
                            'seed_relation': seed_relation, 'candidate_relation': relation,
                            'strength': 'explicit static context' if strong else 'weak shared dependency',
                            'degree': degree, 'gold_after_seal': candidate in gold,
                            'omission': 'not_in_match_pool' if candidate not in pool else 'page_only',
                            'definition': contexts.get(via),
                            'conclusion': 'reachability candidate only; source/task review required'})
    result = {'scope': 'development 30 PR; existing P1 seeds/relations; host-only labels',
              'seeds': 'first 4 complete P1 R first-page results, chosen without gold',
              'degree_cap': 12, 'rows': rows,
              'summary': {strength: {
                  'reachable_tasks': sorted({r['task_id'] for r in rows if r['strength']==strength}),
                  'missed_gold_tasks': sorted({r['task_id'] for r in rows if r['strength']==strength and r['gold_after_seal']}),
                  'outside_pool_gold_tasks': sorted({r['task_id'] for r in rows if r['strength']==strength and r['gold_after_seal'] and r['omission']=='not_in_match_pool'})}
                  for strength in ('explicit static context', 'weak shared dependency')},
              'p1_seal_sha256': sha(P1/'rankings-seal.json')}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT/'launch-audit.json'
    if path.exists():
        raise ValueError('Launch audit already exists')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
