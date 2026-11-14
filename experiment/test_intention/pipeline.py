"""Repeatable source-only representation preparation and generation."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

from .first30 import DEFAULT_OUTPUT, SOURCE_ROOT, BENCH_REL
from .generation import Generator, render
from .static import build, batches, digest, write


def inputs(output):
    scope = json.loads((output / 'scope.json').read_text())
    sys.path.insert(0, str(SOURCE_ROOT / BENCH_REL))
    from batch.testcase_identity import inventory

    def one(base):
        repository = SOURCE_ROOT / BENCH_REL / 'batch/baselines' / base / 'repository'
        doc = build(repository, base)
        original = inventory(repository, base)
        if [t['id'] for t in doc['tests']] != [t['id'] for t in original['entries']]:
            raise ValueError('Representation identity inventory differs: ' + base)
        packet_list = list(batches(doc))
        write(output / 'static' / (base + '.json'), doc)
        write(output / 'packets' / (base + '.json'), packet_list)
        return base, doc['test_count'], packet_list

    unique, counts = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(one, b) for b in scope['base_shas']]):
            base, count, packets = future.result()
            counts[base] = count
            unique.update({digest(p): p for p in packets})
            print(json.dumps({'base': base, 'tests': count, 'batches': len(packets)}), flush=True)
    plan = {'base_count': len(counts), 'raw_test_records': sum(counts.values()),
            'unique_batches': len(unique), 'input_characters': sum(len(json.dumps(p)) for p in unique.values()),
            'maximum_packet_characters': max(len(json.dumps(p)) for p in unique.values()),
            'batch_size': 8, 'max_chars': 64000, 'model': 'deepseek-flash', 'effort': 'high',
            'max_output_tokens_per_call': 16384, 'maximum_validation_repairs': 1,
            'generation_ceiling_cny_peak_price': 200, 'workers': 64,
            'identity_check': 'PASS', 'base_test_counts': counts}
    write(output / 'generation-plan.json', plan)
    print(json.dumps(plan), flush=True)


def generate(output):
    scope = json.loads((output / 'scope.json').read_text())
    generator = Generator(output / 'generation-cache', secret=Path.home() / '.config/sdd-bench/deepseek-api-key')
    all_packets = []
    by_base = {}
    for base in scope['base_shas']:
        packets = json.loads((output / 'packets' / (base + '.json')).read_text())
        by_base[base] = packets
        all_packets.extend(packets)
    result = generator.run(all_packets, workers=64)
    summary = {'unique_batches': len(result), 'generated_batches': sum(r['status'] == 'GENERATED' for r in result.values()),
               'fallback_batches': sum(r['status'] != 'GENERATED' for r in result.values()),
               'calls_in_request_journal': generator.calls, 'peak_price_accounted_or_reserved_cny': generator.reserved_cost_cny,
               'cost_ceiling_cny': generator.max_cost_cny,
               'usage': {key: sum(u.get(key, 0) for r in result.values() for u in r['usage'])
                         for key in ('input_tokens', 'output_tokens', 'total_tokens')}}
    write(output / 'generation-summary.json', summary)
    publish(output)
    print(json.dumps(summary), flush=True)


def publish(output):
    scope = json.loads((output / 'scope.json').read_text())
    generator = Generator(output / 'generation-cache', secret=Path.home() / '.config/sdd-bench/deepseek-api-key')
    for base in scope['base_shas']:
        document = json.loads((output / 'static' / (base + '.json')).read_text())
        packets = json.loads((output / 'packets' / (base + '.json')).read_text())
        manifest = render(document, packets, generator.cache, output / 'representations' / base, generator)
        print(json.dumps({'base': base, 'generated': manifest['generated_count'], 'fallback': manifest['fallback_count']}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('inputs', 'generate', 'publish'))
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    globals()[args.action](args.output.resolve())


if __name__ == '__main__':
    main()
