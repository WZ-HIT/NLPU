"""Seal public queries/rankings first; host-only development evaluation is separate."""
import argparse
from collections import defaultdict
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3

from . import reader
from . import search_view as search

ROOT = Path('/data2/wangzuohit/NLPU-experiments/test-intention')
OUTPUT = ROOT/'p1-20261103-v2'
OLD = ROOT/'compact-v2/representations'
RUN = ROOT/'compact-first30-v1'
ROUND = 'round-fc2b0bbcfbfef43648460ff7'
# Frozen before reading evaluation labels. Preserve concrete API/config symbols.
STOP = set('a an the this that these those i we you it its is are was were be been being '
           'to of for from in on at by with without as and or but if then than so '
           'can could should would will may might must do does did done not no '
           'have has had more some any all other only also when where which who '
           'what how why into out up use using used change changes fix fixes fixed '
           'add adds added update updates updated test tests testing support allow '
           'issue pull request pr see https http www com github code example'.split())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def clauses(text):
    text = re.sub(r'https?://\S+', ' ', text)
    terms, seen = [], set()
    for match in re.finditer(r'\b[A-Za-z_][\w]*(?:[./][\w]+)*', text):
        term = match.group().strip('./')
        folded = term.casefold()
        if folded in STOP or folded in seen or len(term)<2:
            continue
        terms.append(term)
        seen.add(folded)
        if len(terms) == 16:
            break
    return terms


def plan(output):
    if (output/'queries.json').exists():
        raise ValueError('Queries already frozen; refusing overwrite')
    scope = json.loads((RUN/'scope.json').read_text())
    bases = {t['task_id']: t['base_sha'] for t in scope['targets']}
    rows = []
    for pr in scope['prs']:
        task = f'scrapy__scrapy__pr{pr}'
        path = RUN/'execution-root/sdd-bench/scrapy-sdd/batch/runs'/ROUND/'tasks'/task/'experiment-inputs/task.md'
        full = path.read_text()
        title, body = full.split('## Title\n', 1)[1].split('## Body\n', 1)
        public = {'title': title.strip(), 'body': body.strip()}
        rows.append({'task_id': task, 'base_sha': bases[task], **public,
                     'task_input_sha256': search.sha(path),
                     'queries': clauses(public['title']+'\n'+public['body'])})
    if len(rows) != 30 or len({r['task_id'] for r in rows}) != 30:
        raise ValueError('Expected fixed development 30 PRs')
    write(output/'queries.json', {'version': 1, 'source': 'public title/body only', 'mode': 'or',
                                'max_bytes': 6000, 'limit': 25, 'stopwords': sorted(STOP), 'tasks': rows})
    write(output/'query-seal.json', {'queries_sha256': search.sha(output/'queries.json'),
                                   'script_sha256': search.sha(__file__), 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})


def complete_items(page):
    rows = [r for r in page['items'] if 'id' in r]
    fragments = defaultdict(list)
    for item in page['items']:
        if item.get('format') == 'json-text-fragment':
            fragments[item['record']].append(item)
    for pieces in fragments.values():
        if [p['fragment'] for p in pieces] == list(range(pieces[0]['fragments'])):
            rows.append(json.loads(''.join(p['text'] for p in pieces)))
    # Preserve displayed order, including a fully assembled fragmented record.
    order = {}
    for i, item in enumerate(page['items']):
        if 'id' in item:
            order[item['id']] = i
    for record, pieces in fragments.items():
        if [p['fragment'] for p in pieces] == list(range(pieces[0]['fragments'])):
            identity = json.loads(''.join(p['text'] for p in pieces))['id']
            order[identity] = next(i for i, item in enumerate(page['items']) if item.get('record') == record)
    return sorted(rows, key=lambda row: order[row['id']])


def all_pieces(rows):
    # Same fragmentation threshold and Unicode units as the public legacy pager.
    pieces = []
    for number, row in enumerate(rows):
        text = search.encoded(row)
        if len(text.encode()) <= 2400:
            pieces.append(row)
        else:
            chunks = [text[i:i+300] for i in range(0, len(text), 300)]
            pieces.extend({'record': number, 'fragment': i, 'fragments': len(chunks),
                           'format': 'json-text-fragment', 'text': chunk} for i, chunk in enumerate(chunks))
    return pieces


def lookup_cost(card, pager):
    offset = calls = size = 0
    while True:
        page = pager([card], offset, 25, 6000)
        calls += 1
        size += len(search.encoded(page).encode())+1
        if page['next_offset'] is None:
            return {'show_calls': calls, 'show_bytes': size}
        offset = page['next_offset']


def rankings(output):
    if (output/'rankings-seal.json').exists():
        raise ValueError('Rankings already sealed; refusing overwrite')
    query_seal = json.loads((output/'query-seal.json').read_text())
    if query_seal['queries_sha256'] != search.sha(output/'queries.json') or query_seal['script_sha256'] != search.sha(__file__):
        raise ValueError('Query/script changed after freeze')
    config = json.loads((output/'queries.json').read_text())
    grouped = defaultdict(list)
    for task in config['tasks']:
        grouped[task['base_sha']].append(task)
    sealed_files, bundle_hashes, checks = {}, {}, []
    for base, tasks in sorted(grouped.items()):
        root, old = output/'representations'/base, OLD/base
        manifest = json.loads((root/'manifest.json').read_text())
        for name, digest in manifest['files'].items():
            if search.sha(root/name) != digest:
                raise ValueError('Bundle changed: '+name)
        if search.sha(root/'.evidence.sqlite3') != search.sha(old/'.evidence.sqlite3'):
            raise ValueError('Evidence changed')
        bundle_hashes[base] = {'new': search.sha(root/'manifest.json'), 'old': search.sha(old/'manifest.json')}
        spec = importlib.util.spec_from_file_location('legacy_reader', old/'read.py')
        legacy = importlib.util.module_from_spec(spec); spec.loader.exec_module(legacy)
        docs, stats = search.load_index(root)
        with reader.connect(root) as db:
            records = {d['id']: d['record'] for d in search.read_records(db)}
            for task in tasks:
                queries = task['queries']
                expanded = search.rank(docs, stats, queries, sort='id')
                # Original SQLite JSON preserves indentation/escaping. Use the actual legacy predicate.
                old_ids = [i for i, text in db.execute('SELECT id,intention FROM tests ORDER BY id')
                           if not queries or any(q.casefold() in (i+' '+text).casefold() for q in queries)]
                variants = {'L': (old_ids, [records[i]['card'] for i in old_ids], False)}
                ids = [d['id'] for d, _, _ in expanded]
                variants['T'] = (ids, [records[i]['card'] for i in ids], False)
                for label, sort in [('S', 'id'), ('R', 'field-bm25-v1'), ('F', 'tfidf')]:
                    ranked = expanded if sort == 'id' else search.rank(docs, stats, queries, sort=sort)
                    rows = [search.short_row(d, hits, score, records[d['id']]) for d, hits, score in ranked]
                    variants[label] = ([d['id'] for d, _, _ in ranked], rows, True)
                task_checks = {'task_id': task['task_id'], 'hit_references_verified': 0, 'pagination_units_verified': 0}
                for label, (ranked_ids, rows, short) in variants.items():
                    binding = hashlib.sha256(search.encoded({'base': bundle_hashes[base], 'queries': queries, 'variant': label,
                                                            'reader': search.sha(root/'read.py'), 'helper': search.sha(root/'search_view.py'),
                                                            'limit': 25, 'max_bytes': 6000}).encode()).hexdigest()
                    page = search.search_page(rows, binding, 0, 25, 6000, reader.page) if short else legacy.page(rows, 0, 25, 6000)
                    visible = complete_items(page)
                    text = search.encoded(page)+'\n'
                    if len(text.encode())>6000:
                        raise ValueError('Output exceeds fixed budget')
                    if short:
                        for row in visible:
                            if row['hit']:
                                hit = row['hit']; evidence = search.lookup(db, row['id'], hit['ref'])
                                if evidence['value'][hit['start']:hit['end']] != hit['text']:
                                    raise ValueError('Unfaithful snippet')
                                task_checks['hit_references_verified'] += 1
                        # Verify every page unit in order; no duplicated or omitted fragment.
                        expected, got, offset = all_pieces(rows), [], 0
                        while True:
                            part = search.search_page(rows, binding, offset, 25, 6000, reader.page)
                            got.extend(part['items'])
                            if part['next_cursor'] is None:
                                break
                            offset = search.cursor_offset(part['next_cursor'], binding)
                        if got != expected:
                            raise ValueError('Pagination changed result sequence')
                        task_checks['pagination_units_verified'] += len(got)
                    relative = Path('rankings')/task['task_id']/(label+'.json')
                    write(output/relative, {'task_id': task['task_id'], 'base_sha': base, 'variant': label,
                          'ranked_ids': ranked_ids, 'visible_ids': [r['id'] for r in visible],
                          'output_utf8_bytes': len(text.encode()),
                          'returned_units': len(page['items']), 'visible_complete_tests': len(visible),
                          'first_result_lookup': lookup_cost(records[ranked_ids[0]]['card'], legacy.page) if ranked_ids else None})
                    page_relative = relative.with_suffix('.page.json')
                    (output/page_relative).write_text(text)
                    for name in (relative, page_relative):
                        sealed_files[name.as_posix()] = search.sha(output/name)
                checks.append(task_checks)
                print(json.dumps({'task': task['task_id'], 'stage': 'SEALED_RANKING'}), flush=True)
    write(output/'offline-checks.json', checks)
    sealed_files['offline-checks.json'] = search.sha(output/'offline-checks.json')
    sealed_files['queries.json'] = search.sha(output/'queries.json')
    write(output/'rankings-seal.json', {'version': 1, 'files': sealed_files, 'bundles': bundle_hashes,
          'script_sha256': search.sha(__file__), 'search_sha256': search.sha(search.__file__),
          'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'labels_read': False})


def evaluate(output):
    if (output/'offline-metrics.json').exists():
        raise ValueError('Metrics already exist; refusing overwrite')
    seal = json.loads((output/'rankings-seal.json').read_text())
    for name, digest in seal['files'].items():
        if search.sha(output/name) != digest:
            raise ValueError('Sealed prediction changed: '+name)
    # Host-only labels are opened only after all predictions have been sealed/verified.
    host_path = RUN/'host-comparison/metrics.json'
    host = json.loads(host_path.read_text())
    tasks = json.loads((output/'queries.json').read_text())['tasks']
    rows = []
    for task in tasks:
        task_id = task['task_id']
        gold = set(host['tasks'][task_id]['labels']['testcases'])
        inventory = {r['id'] for r in host['tasks'][task_id]['index']['entries']}
        for variant in 'LTSRF':
            prediction = json.loads((output/'rankings'/task_id/(variant+'.json')).read_text())
            ranked, visible = prediction['ranked_ids'], prediction['visible_ids']
            if not set(ranked) <= inventory or not gold <= inventory or len(set(ranked)) != len(ranked):
                raise ValueError('Identity or denominator mismatch')
            hits = len(set(visible) & gold)
            first = next((i+1 for i, identity in enumerate(visible) if identity in gold), None)
            rows.append({'task_id': task_id, 'variant': variant, 'gold': len(gold), 'hits': hits,
                         'recall_at_6000B': hits/len(gold) if gold else None,
                         'candidate_precision': hits/len(visible) if visible else 0,
                         'pool_hits': len(set(ranked)&gold), 'pool_size': len(ranked),
                         'first_target_visible_rank': first, 'reciprocal_rank_at_budget': 1/first if first else 0,
                         **{key: prediction[key] for key in ('output_utf8_bytes', 'returned_units', 'visible_complete_tests', 'first_result_lookup')}})
    summaries = {}
    for variant in 'LTSRF':
        group = [r for r in rows if r['variant'] == variant]
        positive = [r for r in group if r['gold']]
        total_gold = sum(r['gold'] for r in group)
        summaries[variant] = {'tasks': len(group), 'positive_tasks': len(positive), 'gold': total_gold,
            'hits': sum(r['hits'] for r in group),
            'macro_recall_at_6000B': sum(r['recall_at_6000B'] for r in positive)/len(positive),
            'micro_recall_at_6000B': sum(r['hits'] for r in group)/total_gold,
            'hit_at_budget': sum(r['hits']>0 for r in positive)/len(positive),
            'mrr_at_budget': sum(r['reciprocal_rank_at_budget'] for r in positive)/len(positive),
            'micro_candidate_precision': sum(r['hits'] for r in group)/max(1, sum(r['visible_complete_tests'] for r in group)),
            'macro_pool_recall': sum(r['pool_hits']/r['gold'] for r in positive)/len(positive),
            'mean_visible_tests': sum(r['visible_complete_tests'] for r in group)/len(group),
            'mean_output_bytes': sum(r['output_utf8_bytes'] for r in group)/len(group),
            'no_positive': [{'task_id': r['task_id'], 'pool_size': r['pool_size'], 'visible_complete_tests': r['visible_complete_tests']} for r in group if not r['gold']]}
    paired = []
    for before, after in [('L', 'T'), ('T', 'S'), ('S', 'R'), ('S', 'F'), ('L', 'R')]:
        pairs = [(next(r for r in rows if r['task_id']==t['task_id'] and r['variant']==before),
                  next(r for r in rows if r['task_id']==t['task_id'] and r['variant']==after)) for t in tasks]
        paired.append({'before': before, 'after': after,
                       'improved_prs': [a['task_id'] for a, b in pairs if b['hits']>a['hits']],
                       'regressed_prs': [a['task_id'] for a, b in pairs if b['hits']<a['hits']],
                       'same_prs': sum(b['hits']==a['hits'] for a, b in pairs)})
    write(output/'offline-metrics.json', {'scope': 'development 30 PR, one deterministic public query per PR, not SDD predictions',
          'rankings_seal_sha256': search.sha(output/'rankings-seal.json'),
          'host_labels_source_sha256': search.sha(host_path), 'summaries': summaries, 'paired': paired, 'rows': rows})
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('plan', 'rank', 'evaluate'))
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    {'plan': plan, 'rank': rankings, 'evaluate': evaluate}[args.stage](args.output)


if __name__ == '__main__':
    main()
