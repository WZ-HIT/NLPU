"""TI-13: read-only, label-free coverage audit. Never instantiates Generator.

Inputs are original static/packet/cache journals, public bases, and current
published SQLite evidence. Outputs are host audit material, not Agent inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tokenize

from .generation import INSTRUCTIONS, PROMPT_VERSION, validate
from .static import digest, generation_input, write

ROOT = Path(__file__).resolve().parents[2]
STORE = Path('/data2/wangzuohit/NLPU-experiments/test-intention')
OPTIONS = dict(model='deepseek-flash', effort='high', max_output_tokens=16384,
               prompt_version=PROMPT_VERSION, instructions_sha256=digest(INSTRUCTIONS))
SEMANTIC_FIELDS = ('summary', 'operations', 'inputs', 'environment_mock', 'scenarios', 'uncertainties')
STATIC_FIELDS = ('calls', 'assertions', 'assignments', 'conditions', 'mock', 'parameters', 'dependency_links')
REASONS = ('GENERATED', 'NOT_SCHEDULED', 'BUDGET_REJECTED_LIMIT_UNKNOWN',
           'OUTPUT_INCOMPLETE', 'PROVIDER_OR_NETWORK_ERROR', 'FORMAT_ERROR',
           'EVIDENCE_REFERENCE_ERROR', 'OVERSIZE_INPUT', 'REQUEST_WITHOUT_FINAL_CACHE',
           'OTHER_UNKNOWN')


def reason(cache, requests):
    """Classify the recorded terminal outcome, not a hypothetical root cause."""
    if cache is None:
        return 'REQUEST_WITHOUT_FINAL_CACHE' if requests else 'NOT_SCHEDULED'
    if cache['status'] == 'GENERATED':
        return 'GENERATED'
    error = str(cache.get('error') or '')
    if 'Configured generation request or cost ceiling reached' in error:
        return 'BUDGET_REJECTED_LIMIT_UNKNOWN'
    if 'Prior request exists without final cache' in error:
        return 'REQUEST_WITHOUT_FINAL_CACHE'
    if 'Scenario evidence must reference own test and supplied context' in error:
        return 'EVIDENCE_REFERENCE_ERROR'
    if 'exceeds 64000 character ceiling' in error:
        return 'OVERSIZE_INPUT'
    if 'Provider response did not complete' in error:
        return 'OUTPUT_INCOMPLETE'
    if any(x in error for x in ('Provider HTTP status', 'TimeoutError', 'URLError',
                                 'ConnectionError', 'SSLError', 'HTTPError')):
        return 'PROVIDER_OR_NETWORK_ERROR'
    if any(x in error for x in ('Expected ', 'Wrong ', 'Invalid identity', 'At least one scenario',
                                 'Test IDs missing', 'Expecting ', 'Unterminated ', 'Extra data',
                                 'Invalid control character')):
        return 'FORMAT_ERROR'
    return 'OTHER_UNKNOWN'


def complexity(test):
    """Overlapping, public-source strata; not a score or inferred difficulty."""
    facts = test['static']
    lines = test['source']['end_line'] - test['source']['start_line'] + 1
    return {'lines:' + ('1-20' if lines <= 20 else '21-60' if lines <= 60 else '61+') ,
            'contexts:' + ('0-4' if len(test['contexts']) <= 4 else '5+'),
            'conditions:' + ('present' if facts.get('conditions') else 'absent'),
            'mock:' + ('present' if facts.get('mock') else 'absent'),
            'uncertainty:' + ('present' if test.get('uncertainty') else 'absent')}


def dump_csv(path, rows):
    if not rows:
        path.write_text('')
        return
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                         for k, v in row.items()} for row in rows)


def audit(original, current, baselines, destination):
    if destination.exists():
        raise ValueError('Refusing to overwrite audit output')
    destination.mkdir(parents=True)
    sources, violations = {}, []

    def read(path):
        raw = path.read_bytes()
        sources[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    def check(ok, code, **context):
        if not ok:
            violations.append({'code': code, **context})

    scope = read(original/'scope.json')
    plan = read(original/'generation-plan.json')
    old_summary = read(original/'generation-summary.json')
    journal, request_rows = defaultdict(list), []
    for path in sorted((original/'generation-cache/requests').glob('*.json')):
        entry = read(path)
        entry = {**entry, 'journal_id': path.stem,
                 'request_id_origin': 'RECORDED' if entry.get('request_id') else 'LEGACY_ID_NOT_RECORDED'}
        journal[entry['input_sha256']].append(entry)
        usage = entry.get('usage')
        complete = isinstance(usage, dict) and {'input_tokens', 'output_tokens'} <= usage.keys()
        request_rows.append({**entry, 'path': str(path), 'sha256': sources[str(path.resolve())],
                             'usage_complete': complete,
                             'cost_kind': 'HISTORICAL_FORMULA_ESTIMATE' if 'accounted_cost_cny' in entry
                             else 'RESERVATION_NOT_ACTUAL_COST'})
        check(not entry.get('request_id') or path.stem == entry['request_id'], 'REQUEST_FILENAME_MISMATCH', path=str(path))
    cache = {}
    for path in sorted((original/'generation-cache').glob('*.json')):
        # Non-hash metadata files are inventoried, never treated as input caches.
        item = read(path)
        if 'packet' not in item:
            continue
        key = path.stem
        check(key == digest({'packet': item['packet'], 'options': item['options']}) == item['input_sha256'],
              'CACHE_IDENTITY_MISMATCH', key=key)
        check(item['options'] == OPTIONS, 'CACHE_OPTIONS_DIFFER', key=key)
        validation_error = None
        if item['status'] == 'GENERATED':
            try:
                validate(item['result'], item['packet'])
            except (ValueError, TypeError, KeyError) as exc:
                validation_error = str(exc)
                check(False, 'GENERATED_CACHE_INVALID', key=key, error=validation_error)
        else:
            check(item.get('result') is None, 'FALLBACK_HAS_RESULT', key=key)
        # Keep only compact metadata/results. Packet equality uses its digest.
        cache[key] = {k: v for k, v in item.items() if k not in ('packet', 'result')}
        cache[key].update(packet_digest=digest(item['packet']),
                          results={t['id']: t for t in (item.get('result') or {}).get('tests', [])},
                          validation_error=validation_error,
                          cache_path=str(path), cache_sha256=sources[str(path.resolve())])
    print(json.dumps({'phase': 'cache_and_journal', 'caches': len(cache), 'requests': len(request_rows)}), flush=True)

    # Import only the existing gold-free source inventory implementation.
    sys.path.insert(0, str(ROOT/'sdd-bench/scrapy-sdd'))
    from batch.testcase_identity import inventory

    tests, occurrences = [], []
    groups, field_empty, field_missing = defaultdict(Counter), Counter(), Counter()
    seen_keys, used_journals = set(), set()
    for base in scope['base_shas']:
        document = read(original/'static'/f'{base}.json')
        packets = read(original/'packets'/f'{base}.json')
        full_manifest = read(original/'representations'/base/'manifest.json')
        bundle = current/base
        manifest = read(bundle/'manifest.json')
        repository = (baselines/base/'repository').resolve()
        original_manifest_hashes = document['source_files']
        check(manifest['source_files'] == original_manifest_hashes == full_manifest['source_files'],
              'SOURCE_MANIFEST_DIFFER', base=base)
        check(document['base_sha'] == manifest['base_sha'] == full_manifest['base_sha'] == base,
              'BASE_IDENTITY_MISMATCH', base=base)
        source_lines = {}
        for relative, checksum in original_manifest_hashes.items():
            path = repository/relative
            safe = not path.is_symlink() and path.resolve().is_relative_to(repository) and path.is_file()
            check(safe, 'UNSAFE_OR_MISSING_BASE_SOURCE', base=base, path=relative)
            if not safe:
                continue
            raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            sources[str(path)] = raw_hash
            check(raw_hash == checksum, 'BASE_SOURCE_HASH_MISMATCH', base=base, path=relative)
            if relative.startswith(('tests/', 'test/')):
                with tokenize.open(path) as stream:
                    source_lines[relative] = stream.read().splitlines(True)
        actual = inventory(repository, base)
        check(not actual['errors'], 'BASE_INVENTORY_ERRORS', base=base, errors=actual['errors'])
        source_index = {t['id']: t for t in actual['entries']}
        static_tests = {t['id']: t for t in document['tests']}
        check(len(static_tests) == len(document['tests']) == document['test_count'] == len(source_index),
              'STATIC_COUNT_MISMATCH', base=base)
        check(static_tests.keys() == source_index.keys(), 'STATIC_ID_INVENTORY_MISMATCH', base=base)

        packet_for = {}
        for ordinal, packet in enumerate(packets):
            key = digest({'packet': packet, 'options': OPTIONS})
            seen_keys.add(key)
            record = cache.get(key)
            requests = journal.get(key, [])
            used_journals.update(r['journal_id'] for r in requests)
            members = packet['tests']
            if all(t['id'] in static_tests for t in members):
                check(packet == generation_input([static_tests[t['id']] for t in members]),
                      'PACKET_STATIC_MISMATCH', base=base, key=key)
            else:
                check(False, 'PACKET_UNKNOWN_TEST', base=base, key=key)
            if record:
                check(record['packet_digest'] == digest(packet), 'PACKET_CACHE_MISMATCH', base=base, key=key)
            status = record['status'] if record else 'MISSING_CACHE'
            why = reason(record, requests)
            occurrences.append({'base_sha': base, 'packet_ordinal': ordinal, 'cache_key': key,
                                'tests': len(members), 'status': status, 'reason': why})
            for member in members:
                check(member['id'] not in packet_for, 'DUPLICATE_PACKET_TEST', base=base, id=member['id'])
                packet_for[member['id']] = (ordinal, key, record, requests, why)
        check(packet_for.keys() == static_tests.keys(), 'PACKET_INVENTORY_MISMATCH', base=base)

        database = bundle/'.evidence.sqlite3'
        sources[str(database.resolve())] = hashlib.sha256(database.read_bytes()).hexdigest()
        check(sources[str(database.resolve())] == manifest['files']['.evidence.sqlite3'],
              'CURRENT_DB_HASH_MISMATCH', base=base)
        with sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1', uri=True) as db:
            check(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'CURRENT_DB_INVALID', base=base)
            published = {i: dict(card=json.loads(card), intention=json.loads(semantics),
                                 facts=json.loads(facts), location=json.loads(location))
                         for i, card, semantics, facts, location in
                         db.execute('SELECT id,card,intention,facts,location FROM tests')}
        check(published.keys() == static_tests.keys(), 'CURRENT_ID_INVENTORY_MISMATCH', base=base)
        for identity, test in static_tests.items():
            ordinal, key, record, requests, why = packet_for[identity]
            status = record['status'] if record else 'MISSING_CACHE'
            source, indexed, visible = test['source'], source_index[identity], published[identity]
            expected_location = {k: source[k] for k in ('path', 'start_line', 'end_line')}
            check(all(indexed[k] == source[k] for k in expected_location), 'SOURCE_LOCATION_MISMATCH', base=base, id=identity)
            check(all(visible['location'][k] == v for k, v in expected_location.items()), 'CURRENT_LOCATION_MISMATCH', base=base, id=identity)
            span = ''.join(source_lines[test['path']][source['start_line']-1:source['end_line']])
            check(source['source'] == span and source['source_sha256'] == digest(span),
                  'SOURCE_SPAN_MISMATCH', base=base, id=identity)
            check(visible['card']['status'] == status, 'CURRENT_STATUS_MISMATCH', base=base, id=identity)
            check(all(visible['facts'].get(k) == test['static'].get(k) for k in STATIC_FIELDS if k != 'dependency_links'),
                  'CURRENT_FACTS_MISMATCH', base=base, id=identity)
            expected_semantic = (record or {}).get('results', {}).get(identity)
            # Reader stores {} for fallback; no semantic description is generated.
            check((visible['intention'] or None) == expected_semantic,
                  'CURRENT_SEMANTIC_MISMATCH', base=base, id=identity)
            missing = [k for k in SEMANTIC_FIELDS if k not in (expected_semantic or {})]
            empty = [k for k in SEMANTIC_FIELDS if k in (expected_semantic or {}) and not expected_semantic[k]]
            field_missing.update(missing)
            if status == 'GENERATED':
                field_empty.update(empty)
            missing_static = [k for k in STATIC_FIELDS if k not in test['static']]
            row = dict(base_sha=base, id=identity, path=test['path'], start_line=source['start_line'],
                       end_line=source['end_line'], source_sha256=source['source_sha256'],
                       source_file_sha256=original_manifest_hashes[test['path']],
                       record_present=True, static_present=not missing_static,
                       semantic_status=status, reason=why,
                       structural_validation='PASS' if status == 'GENERATED' and not record['validation_error'] else 'NOT_APPLICABLE',
                       semantic_quality_review='NOT_PERFORMED_BY_TI13',
                       missing_semantic_fields=missing, empty_semantic_fields=empty,
                       missing_static_fields=missing_static, packet_ordinal=ordinal, cache_key=key,
                       cache_path=(record or {}).get('cache_path'), cache_error=(record or {}).get('error'),
                       request_journal_ids=[r['journal_id'] for r in requests], request_count_for_packet=len(requests),
                       unknown_usage_requests=sum(not isinstance(r.get('usage'), dict) or
                           not {'input_tokens', 'output_tokens'} <= r['usage'].keys() for r in requests),
                       source_line_count=source['end_line']-source['start_line']+1,
                       context_count=len(test['contexts']), condition_count=len(test['static'].get('conditions', [])),
                       mock_count=len(test['static'].get('mock', [])))
            tests.append(row)
            groups[('base', base)][status] += 1
            groups[('file', base+'::'+test['path'])][status] += 1
            for stratum in complexity(test):
                groups[('source_stratum', stratum)][status] += 1
        base_counts = groups[('base', base)]
        check(full_manifest['generated_count'] == base_counts['GENERATED'] and
              full_manifest['fallback_count'] == base_counts['STATIC_FALLBACK'],
              'ORIGINAL_PUBLISH_COUNTS_MISMATCH', base=base)
        print(json.dumps({'phase': 'base_verified', 'base': base, 'counts': dict(base_counts)}), flush=True)

    packets = []
    for key in sorted(seen_keys):
        record, requests = cache.get(key), journal.get(key, [])
        refs = [o for o in occurrences if o['cache_key'] == key]
        packets.append(dict(cache_key=key, packet_digest=(record or {}).get('packet_digest'),
                            base_shas=sorted({o['base_sha'] for o in refs}),
                            versioned_test_records=sum(o['tests'] for o in refs),
                            status=(record or {}).get('status', 'MISSING_CACHE'), reason=reason(record, requests),
                            cache_path=(record or {}).get('cache_path'), cache_sha256=(record or {}).get('cache_sha256'),
                            error=(record or {}).get('error'), attempts=(record or {}).get('attempts', []),
                            request_journal_ids=[r['journal_id'] for r in requests], request_count=len(requests)))
    # Cache directories may contain earlier smoke inputs outside this scope.
    # Keep them visible without treating them as current coverage or corruption.
    extra_cache_keys = sorted(cache.keys()-seen_keys)
    check(not (seen_keys-cache.keys()), 'MISSING_SCOPE_CACHES', missing=sorted(seen_keys-cache.keys()))
    outside_requests = [r for r in request_rows if r['journal_id'] not in used_journals]
    check(all(r['input_sha256'] in extra_cache_keys for r in outside_requests), 'UNREFERENCED_REQUESTS')
    check(len(request_rows) == len({r['journal_id'] for r in request_rows}), 'DUPLICATE_JOURNAL_ID')
    check(len(tests) == plan['raw_test_records'] and len(seen_keys) == plan['unique_batches'], 'ORIGINAL_PLAN_COUNTS_MISMATCH')
    check(len(request_rows) == old_summary['calls_in_request_journal'], 'ORIGINAL_JOURNAL_COUNT_MISMATCH')
    status_counts = Counter(t['semantic_status'] for t in tests)
    packet_counts = Counter(p['status'] for p in packets)
    check(packet_counts['GENERATED'] == old_summary['generated_batches'] and
          packet_counts['STATIC_FALLBACK'] == old_summary['fallback_batches'], 'ORIGINAL_CACHE_COUNTS_MISMATCH')
    group_rows = [dict(group_type=kind, group=value, total=sum(counts.values()),
                       generated=counts['GENERATED'], fallback=counts['STATIC_FALLBACK'],
                       other=sum(v for k, v in counts.items() if k not in ('GENERATED', 'STATIC_FALLBACK')),
                       generated_percent=round(100*counts['GENERATED']/sum(counts.values()), 4))
                  for (kind, value), counts in sorted(groups.items())]
    known_cost = sum(r.get('accounted_cost_cny', 0) for r in request_rows)
    reserved_unknown = sum(r.get('reservation_cny', 0) for r in request_rows if 'accounted_cost_cny' not in r)
    summary = dict(version='ti13-coverage-audit-v1', status='PASS' if not violations else 'FAIL',
                   base_count=len(scope['base_shas']), test_records=len(tests),
                   status_counts=dict(status_counts), unique_test_ids=len({t['id'] for t in tests}),
                   base_packet_occurrences=len(occurrences), unique_input_packets=len(packets),
                   packet_status_counts=dict(packet_counts), request_count=len(request_rows),
                   out_of_scope_cache_keys=extra_cache_keys,
                   scope_request_journal_count=len(used_journals),
                   out_of_scope_request_journals=[r['journal_id'] for r in outside_requests],
                   legacy_request_id_missing_count=sum(not r.get('request_id') for r in request_rows),
                   request_status_counts=dict(Counter(r['status'] for r in request_rows)),
                   test_reason_counts=dict(Counter(t['reason'] for t in tests)),
                   packet_reason_counts=dict(Counter(p['reason'] for p in packets)),
                   missing_semantic_fields=dict(field_missing), generated_empty_fields=dict(field_empty),
                   static_present_count=sum(t['static_present'] for t in tests),
                   structural_pass_count=sum(t['structural_validation'] == 'PASS' for t in tests),
                   semantic_quality_reviews_performed=0,
                   accounting=dict(complete_usage_requests=sum(r['usage_complete'] for r in request_rows),
                                   missing_usage_requests=sum(not r['usage_complete'] for r in request_rows),
                                   historical_formula_cost_cny=known_cost,
                                   unknown_spend_reservation_cny=reserved_unknown,
                                   actual_provider_invoice_cost_cny=None,
                                   historical_request_limit=4000, historical_cost_ceiling_cny=old_summary['cost_ceiling_cny'],
                                   cap_at_rejection='NOT_RECORDED; request_count below limit supports cost-cap inference only'),
                   model_calls=0, labels_read=False, original_sources_modified=False,
                   quality_note='Structural/reference validity does not establish semantic correctness.',
                   strata_note='Overlapping public-source proxies; no causal or independent-sample interpretation.',
                   current_reading_scope='All current SQLite tests checked against original static inputs and generation caches; raw full-record JSON files not rehashed individually.',
                   violations=violations)
    for name, rows in [('coverage', tests), ('packets', packets), ('packet-occurrences', occurrences),
                       ('requests', request_rows), ('coverage-groups', group_rows)]:
        write(destination/(name+'.json'), rows)
        dump_csv(destination/(name+'.csv'), rows)
    write(destination/'summary.json', summary)
    write(destination/'sources.json', {'version': 'ti13-sources-v1', 'sha256': sources,
                                      'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    rows = ['# TI-13 全库覆盖审计', '', '2026-11-04；只读核查，新增模型调用 0，未读取标签。', '',
            f"状态：{summary['status']}。全部 {len(tests):,} 条记录均对应公开 base；不同版本不当作独立样本。", '',
            '| 统计单位 | 数量 |', '| --- | ---: |',
            f"| base | {summary['base_count']} |", f'| 版本化测试条目 | {len(tests):,} |',
            f"| 已生成语义 | {status_counts['GENERATED']:,} |", f"| 静态回退 | {status_counts['STATIC_FALLBACK']:,} |",
            f'| base 内输入包次数 | {len(occurrences):,} |', f'| 跨 base 去重输入包 | {len(packets):,} |',
            f'| 请求账本条数 | {len(request_rows):,} |', '',
            '| 最终原因 | 测试条目 | 去重输入包 |', '| --- | ---: | ---: |']
    for why in REASONS:
        rows.append(f"| {why} | {summary['test_reason_counts'].get(why,0):,} | {summary['packet_reason_counts'].get(why,0):,} |")
    rows += ['', '逐 base 覆盖：', '', '| base | 测试数 | 已生成 | 回退 | 已生成比例 |', '| --- | ---: | ---: | ---: | ---: |']
    for row in group_rows:
        if row['group_type'] == 'base':
            rows.append(f"| {row['group']} | {row['total']} | {row['generated']} | {row['fallback']} | {row['generated_percent']:.2f}% |")
    rows += ['', '公开源码分层（各类分层相互重叠，不能相加）：', '',
             '| 分层 | 测试数 | 已生成 | 回退 | 已生成比例 |', '| --- | ---: | ---: | ---: | ---: |']
    for row in group_rows:
        if row['group_type'] == 'source_stratum':
            rows.append(f"| {row['group']} | {row['total']} | {row['generated']} | {row['fallback']} | {row['generated_percent']:.2f}% |")
    rows += ['', '生成错误表示输入包的最终记录；成功请求和修复请求均在 requests 中单独保留。',
             f'账本 {len(request_rows)} 条中，范围内 {len(used_journals)} 条；范围外 {len(outside_requests)} 条单列，不计入当前输入包覆盖。旧迁移记录没有原请求ID时保留缺失，使用文件名作为账本ID。',
             '预算拒绝只归为“触发上限未明确”。最终请求数低于 4000，可支持费用限制的推断，但不能重建每次并发拒绝时的预算。',
             f'历史公式估算费用 {known_cost:.6f} 元；未知消费保留预留 {reserved_unknown:.6f} 元；均不是实际账单。',
             f"缺完整 usage 的请求 {summary['accounting']['missing_usage_requests']} 次，未填成零消费。",
             '空数组和字段不存在分开统计；已有意图中的空输入、mock、未知项不自动算错误。',
             '全部已生成缓存重新做结构和引用校验。TI-13 没有开展语义质量人工审查，质量审查数量记为 0。',
             '当前 SQLite 中逐条核对身份、位置、静态事实和完整语义。原完整 JSON 目录仅使用 manifest 作来源连接，未逐文件重哈希。',
             '覆盖缺口可用于生成计划；已知目标上的历史覆盖报告继续留在旧 host-comparison，不进入本审计或调度输入。',
             '', 'coverage.json/csv：逐测试；packets：缓存与请求关联；packet-occurrences：跨 base 复用；requests：实际账本；coverage-groups：base/文件/复杂度；sources：输入哈希。', '']
    (destination/'report.md').write_text('\n'.join(rows))
    write(destination/'completion.json', {'status': summary['status'], 'model_calls': 0,
         'output_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(destination.iterdir()) if p.is_file()}})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, default=STORE/'first30-v1')
    parser.add_argument('--current', type=Path, default=STORE/'p2-20261103-v1/representations')
    parser.add_argument('--baselines', type=Path, default=ROOT/'sdd-bench/scrapy-sdd/batch/baselines')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = audit(args.original.resolve(), args.current.resolve(), args.baselines.resolve(), args.output.resolve())
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if summary['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
