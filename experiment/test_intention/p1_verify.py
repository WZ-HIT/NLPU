"""Independent page/metric recomputation and actual frozen-reader smoke checks."""
from collections import defaultdict
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import time

from .p1_offline import OUTPUT, RUN
from .search_view import sha


def visible_ids(page):
    """Independently assemble only complete records from the displayed page."""
    identities, fragments = [], defaultdict(dict)
    for position, item in enumerate(page['items']):
        if 'id' in item:
            identities.append((position, item['id']))
        else:
            fragments[item['record']][item['fragment']] = (position, item)
    for parts in fragments.values():
        expected = next(iter(parts.values()))[1]['fragments']
        if set(parts) == set(range(expected)):
            text = ''.join(parts[i][1]['text'] for i in range(expected))
            identities.append((parts[0][0], json.loads(text)['id']))
    return [identity for _, identity in sorted(identities)]


def main():
    seal = json.loads((OUTPUT/'rankings-seal.json').read_text())
    for name, digest in seal['files'].items():
        assert sha(OUTPUT/name) == digest, name
    queries = json.loads((OUTPUT/'queries.json').read_text())['tasks']
    metrics = json.loads((OUTPUT/'offline-metrics.json').read_text())
    labels = json.loads((RUN/'host-comparison/metrics.json').read_text())['tasks']
    checks, results = [], []
    for task in queries:
        identity = task['task_id']
        gold = set(labels[identity]['labels']['testcases'])
        for variant in 'LTSRF':
            directory = OUTPUT/'rankings'/identity
            prediction = json.loads((directory/(variant+'.json')).read_text())
            raw = (directory/(variant+'.page.json')).read_bytes()
            visible = visible_ids(json.loads(raw))
            assert len(raw) <= 6000
            assert len(raw) == prediction['output_utf8_bytes']
            assert visible == prediction['visible_ids']
            hits = len(set(visible)&gold)
            row = next(r for r in metrics['rows'] if r['task_id']==identity and r['variant']==variant)
            assert row['hits'] == hits and row['gold'] == len(gold)
            if gold:
                results.append((variant, hits, len(gold)))
        root = OUTPUT/'representations'/task['base_sha']
        for variant, sort in [('S', 'id'), ('R', 'field-bm25-v1'), ('F', 'tfidf')]:
            command = ['python3', '-B', str(root/'read.py'), 'search', '--sort', sort,
                       '--limit', '25', '--max-bytes', '6000']
            for query in task['queries']:
                command.extend(['--query', query])
            start = time.monotonic()
            run = subprocess.run(command, capture_output=True, timeout=90)
            elapsed = time.monotonic()-start
            assert run.returncode == 0, run.stderr.decode()
            page = json.loads(run.stdout)
            expected = json.loads((OUTPUT/'rankings'/identity/(variant+'.page.json')).read_text())
            assert page['items'] == expected['items']
            assert visible_ids(page) == visible_ids(expected)
            assert len(run.stdout) == len((OUTPUT/'rankings'/identity/(variant+'.page.json')).read_bytes())
            assert not (root/'__pycache__').exists()
            checks.append({'task_id': identity, 'variant': variant, 'returncode': run.returncode,
                           'output_bytes': len(run.stdout), 'seconds': elapsed, 'pass': True})
        print(json.dumps({'task_id': identity, 'frozen_reader_variants': 3, 'pass': True}), flush=True)
    for variant in 'LTSRF':
        rows = [(hits, count) for v, hits, count in results if v == variant]
        macro = sum((Fraction(h, n) for h, n in rows), Fraction())/len(rows)
        micro = Fraction(sum(h for h, _ in rows), sum(n for _, n in rows))
        assert abs(float(macro)-metrics['summaries'][variant]['macro_recall_at_6000B'])<1e-12
        assert abs(float(micro)-metrics['summaries'][variant]['micro_recall_at_6000B'])<1e-12
    # Confirm actual reader calls left the bundle inventory/content intact.
    from batch.test_intention import verify_bundle
    for base in {t['base_sha'] for t in queries}:
        verify_bundle(OUTPUT/'representations'/base/'manifest.json', base)
    result = {'pass': True, 'independent_pages': 150, 'public_cli_checks': len(checks),
              'bases': len({t['base_sha'] for t in queries}), 'checks': checks,
              'metrics_source_sha256': sha(OUTPUT/'offline-metrics.json'),
              'ranking_seal_sha256': sha(OUTPUT/'rankings-seal.json'), 'model_calls': 0}
    (OUTPUT/'verification.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
