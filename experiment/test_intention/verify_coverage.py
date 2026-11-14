"""Independent TI-13 artifact/count/journal/source-hash verification, no gold."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def verify(directory):
    read = lambda p: json.loads(p.read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    canonical = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':')).encode()).hexdigest()
    completion = read(directory/'completion.json')
    assert completion['status'] == 'PASS'
    for name, checksum in completion['output_sha256'].items():
        assert sha(directory/name) == checksum, name
    inputs = read(directory/'sources.json')
    for name, checksum in inputs['sha256'].items():
        assert sha(Path(name)) == checksum, name
    source = Path(__file__).with_name('coverage_audit.py')
    assert sha(source) == inputs['script_sha256']
    summary = read(directory/'summary.json')
    tests, packets, occurrences, requests = [read(directory/(name+'.json')) for name in
                                            ('coverage', 'packets', 'packet-occurrences', 'requests')]
    assert len(tests) == summary['test_records']
    assert len({(t['base_sha'],t['id']) for t in tests}) == len(tests)
    assert len({t['base_sha'] for t in tests}) == summary['base_count']
    assert Counter(t['semantic_status'] for t in tests) == summary['status_counts']
    assert Counter(t['reason'] for t in tests) == summary['test_reason_counts']
    assert Counter(p['reason'] for p in packets) == summary['packet_reason_counts']
    assert len(packets) == len({p['cache_key'] for p in packets}) == summary['unique_input_packets']
    assert len(occurrences) == summary['base_packet_occurrences']
    assert sum(o['tests'] for o in occurrences) == len(tests)
    journals = {r['journal_id']: r for r in requests}
    assert len(journals) == len(requests) == summary['request_count']
    used = {i for p in packets for i in p['request_journal_ids']}
    assert len(used) == summary['scope_request_journal_count']
    assert set(journals)-used == set(summary['out_of_scope_request_journals'])
    occurrence_map = {(o['base_sha'],o['packet_ordinal']):o for o in occurrences}
    test_keys = Counter()
    for test in tests:
        occurrence = occurrence_map[(test['base_sha'],test['packet_ordinal'])]
        assert occurrence['cache_key'] == test['cache_key']
        assert occurrence['status'] == test['semantic_status']
        test_keys[test['cache_key']] += 1
    for packet in packets:
        cache = read(Path(packet['cache_path']))
        assert packet['cache_key'] == cache['input_sha256'] == canonical({'packet':cache['packet'], 'options':cache['options']})
        assert test_keys[packet['cache_key']] == packet['versioned_test_records']
        assert cache['status'] == packet['status']
        logs = [journals[i] for i in packet['request_journal_ids']]
        assert all(r['input_sha256'] == packet['cache_key'] for r in logs)
        # Join by provider response identity as well as the input hash. Repairs
        # must remain distinct and cache usage must match the actual journal.
        by_response = {r['response_id']:r for r in logs}
        attempts = [a for a in cache['attempts'] if a.get('response_id')]
        assert {a['response_id'] for a in attempts} == set(by_response)
        assert cache['usage'] == [by_response[a['response_id']]['usage'] for a in attempts]
        if packet['reason'] == 'BUDGET_REJECTED_LIMIT_UNKNOWN':
            assert not logs
    assert abs(sum(r.get('accounted_cost_cny',0) for r in requests)-
               summary['accounting']['historical_formula_cost_cny']) < 1e-8
    groups = read(directory/'coverage-groups.json')
    for kind in ('base','file'):
        assert sum(g['total'] for g in groups if g['group_type'] == kind) == len(tests)
        assert sum(g['generated'] for g in groups if g['group_type'] == kind) == summary['status_counts']['GENERATED']
    return dict(status='PASS', version='ti13-independent-verification-v1', test_records=len(tests),
                unique_packets=len(packets), scope_journal_entries=len(used), input_files_rehashed=len(inputs['sha256']),
                cache_attempt_response_usage_join='PASS', model_calls=0, labels_read=False,
                audit_completion_sha256=sha(directory/'completion.json'), verifier_sha256=sha(Path(__file__)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Refusing to overwrite verification')
    result = verify(args.audit.resolve())
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
