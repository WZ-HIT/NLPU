"""Host-only P0 diagnosis. Reads sealed traces; never launches Agents."""
from __future__ import annotations
import argparse
import collections
import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose(root: Path, output: Path):
    if output.exists():
        raise ValueError('Diagnosis output already exists; use a new version')
    metrics_path = root / 'host-comparison/metrics.json'
    metrics = json.loads(metrics_path.read_text())
    old_evidence = json.loads((root / 'trace-analysis/evidence.json').read_text())
    by_key = {(r['task_id'], r['method']): r for r in metrics['rows']}
    run_root = next((root / 'execution-root/sdd-bench/scrapy-sdd/batch/runs').glob('round-*'))
    ledger = [json.loads(line) for line in (run_root / 'ledger.jsonl').read_text().splitlines()]
    rows = []
    sources = {'metrics': {'path': str(metrics_path), 'sha256': digest(metrics_path)},
               'ledger': {'path': str(run_root / 'ledger.jsonl'), 'sha256': digest(run_root / 'ledger.jsonl')}}
    for prior in old_evidence['traces']:
        path = Path(prior['log'])
        assert digest(path) == prior['log_sha256']
        task, method = prior['task_id'], prior['method']
        measured = by_key[task, method]
        events = [(n, json.loads(line)) for n, line in enumerate(path.open(), 1)]
        commands = [(n, e['item']) for n, e in events if e['type'] == 'item.completed' and e.get('item', {}).get('type') == 'command_execution']
        completed = [n for n, e in events if e['type'] == 'turn.completed']
        errors = [(n, e.get('message', e.get('error', {}).get('message', ''))) for n, e in events if e['type'] in {'error', 'turn.failed'}]
        budget = next(((n, s) for n, s in errors if 'budget exhausted' in s), None)
        payment = next(((n, s) for n, s in errors if '402' in s and 'Balance' in s), None)
        failure_path = run_root / 'execution-events' / f'{task}-{method}-FAILED.json'
        failure = json.loads(failure_path.read_text()) if failure_path.exists() else None
        reason = ('ROLLOUT_BUDGET_EXHAUSTED' if budget else 'PROVIDER_INSUFFICIENT_BALANCE' if payment else
                  'DRAFT_ROOT_ARRAY_HOST_EXCEPTION' if failure and "unhashable type: 'dict'" in json.dumps(failure) else
                  'OTHER_FAILURE' if measured['state'] in {'FAILED', 'BLOCKED'} else 'SEALED')
        stops = [e for e in ledger if e['target']['task_id'] == task and e['target']['method'] == method]
        start = next((e['recorded_at_utc'] for e in stops if e['state'] == 'DETECT_RUNNING'), None)
        end = next((e['recorded_at_utc'] for e in reversed(stops) if e['state'] in {'FAILED', 'BLOCKED', 'DETECT_SEALED'}), None)
        seconds = (datetime.fromisoformat(end.replace('Z', '+00:00')) - datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds() if start and end else None
        tool_errors = []
        for n, item in commands:
            text = item.get('aggregated_output', '')
            if item.get('exit_code') in {None, 0}:
                continue
            match = re.search(r'(?:line \d+: )?([\w./-]+): command not found', text)
            blocked = 'bad interpreter: Permission denied' in text
            if not match and not blocked:
                continue
            tool = Path(match[1]).name if match else Path(item['command'].split()[0]).name
            if blocked:
                tool = 'openspec' if '/openspec' in text else 'cc-sdd' if '/cc-sdd' in text else 'UNKNOWN_INTERPRETER'
            same = [(i, c) for i, c in commands if i > n and c.get('exit_code') == 0 and
                    ((tool in {'openspec', 'cc-sdd'} and (tool + '.js' in c['command'] or tool in c['command'] and 'node ' in c['command'])) or
                     re.search(r'(?<![\w/.-])' + re.escape(tool) + r'\s', c['command'])) and c.get('aggregated_output')]
            alternatives = [(i, c) for i, c in commands if i > n and c.get('exit_code') == 0 and tool == 'rg' and re.search(r'\b(grep|find)\b', c['command'])]
            recovery = same[0][0] if same else None
            window_end = recovery or (alternatives[0][0] if alternatives else None)
            window = [c for i, c in commands if window_end is not None and n < i <= window_end]
            tool_errors.append({'line': n, 'tool': tool, 'exit_code': item.get('exit_code'),
                                'recovery_status': 'LATER_SAME_TOOL_OR_NODE_ENTRY_SUCCEEDED' if recovery else 'ALTERNATIVE_SEARCH_OBSERVED_NOT_PROVEN_EQUIVALENT' if alternatives else 'NO_RECOVERY_PROVEN',
                                'recovery_line': recovery, 'alternative_line': alternatives[0][0] if alternatives else None,
                                'elapsed_seconds': None, 'fatal_causality': 'NOT_ESTABLISHED',
                                'recovery_window_commands': len(window) if window_end else None,
                                'recovery_window_output_utf8_bytes': sum(len(c.get('aggregated_output', '').encode()) for c in window) if window_end else None,
                                'window_cost_interpretation': 'Observed interval may include unrelated investigation; not attributable wasted tokens'})
        searches = [c['line'] for c in prior['commands'] if 'planning_directory_search' in c['categories']]
        known = {'openspec': '/workspace/openspec/changes', 'speckit': '/workspace/specs', 'cc-sdd': '/workspace/.kiro/specs'}[method]
        confirmations = [n for n, e in events if e['type'] == 'item.completed' and e.get('item', {}).get('type') == 'agent_message'
                         and known in e['item'].get('text', '') and re.search(r'(?i)mount|writable|confirmed|planning', e['item']['text'])]
        validation = [{'line': n, 'exit_code': c.get('exit_code'), 'kind': 'AGENT_AUTHORED_CHECK_NOT_SHARED_CONTRACT'}
                      for n, c in commands if 'detection-draft.json' in c['command'] and any(s in c['command'] for s in ['assert ', 'json.tool', 'json.load'])]
        draft_states = []
        inventory = {e['id'] for e in metrics['tasks'][task]['index']['entries']}
        gold = set(metrics['tasks'][task]['labels']['testcases'])
        for ref in prior['draft_files']:
            draft = Path(ref['path'])
            value = json.loads(draft.read_text())
            structure = isinstance(value, dict) and set(value) == {'candidates'} and isinstance(value['candidates'], list)
            candidates = value['candidates'] if structure else value if isinstance(value, list) else []
            ids = {c['path'] + '::' + s for c in candidates for s in c.get('symbols', []) if isinstance(c, dict)}
            structure = structure and all(isinstance(c, dict) and set(c) == {'path', 'symbols', 'reason'} and isinstance(c['symbols'], list) and bool(c['symbols']) and all(isinstance(s, str) and s for s in c['symbols']) and isinstance(c['reason'], str) and bool(c['reason']) for c in candidates)
            draft_states.append({'path': str(draft), 'sha256': digest(draft), 'structure_valid': structure,
                                 'invalid_base_ids': sorted(ids - inventory), 'candidate_count': len(ids),
                                 'host_only_retrospective_tp': len(ids & gold), 'host_only_retrospective_fp': len(ids - gold),
                                 'host_only_retrospective_fn': len(gold - ids),
                                 'investigation_completeness': 'UNKNOWN', 'could_have_ended_successfully': 'NOT_PROVEN'})
        usage_path = path.parent / 'token-usage.json'
        usage = json.loads(usage_path.read_text()) if usage_path.exists() else {'status': 'MISSING'}
        if measured['state'] in {'FAILED', 'BLOCKED'}:
            outcome = 'RUN_FAILED'
        elif not gold:
            outcome = 'SUCCESS_FALSE_ALARM' if measured.get('false_alarm_count', 0) else 'SUCCESS_CORRECT_EMPTY'
        else:
            outcome = 'SUCCESS_WITH_PREDICTION' if measured['prediction']['testcases'] else 'SUCCESS_EMPTY_WITH_MISSES'
        roots = [{'hypothesis': 'Total rollout allowance was exhausted; allocation across activities is unknown', 'confidence': 'DIRECT_TERMINATION_ONLY', 'evidence_line': budget[0]}] if budget else []
        if reason == 'DRAFT_ROOT_ARRAY_HOST_EXCEPTION':
            roots = [{'hypothesis': 'Agent and host checked different draft root contracts', 'confidence': 'DIRECT_EVIDENCE', 'evidence': [str(failure_path), *[x['path'] for x in draft_states]]}]
        elif payment:
            roots = [{'hypothesis': 'Provider refused request for insufficient balance', 'confidence': 'DIRECT_EVIDENCE', 'evidence_line': payment[0]}]
        rows.append({'task_id': task, 'method': method, 'run_id': measured['run_id'], 'attempt': measured['attempt'],
                     'log': str(path), 'log_sha256': digest(path), 'state': measured['state'], 'scoring_status': measured['status'],
                     'outcome': outcome, 'direct_stop_reason': reason, 'stop_evidence': failure or errors[-1:] or {'turn_completed_line': completed[-1] if completed else None},
                     'tools': tool_errors, 'planning': {'first_search_line': searches[0] if searches else None,
                     'subsequent_search_lines': searches[1:], 'possible_confirmed_path_lines': confirmations,
                     'searches_after_possible_confirmation': [n for n in searches if confirmations and n > min(confirmations)],
                     'classification': 'CANDIDATE_EVENTS_REQUIRE_CONTEXT_REVIEW_NOT_ALL_REDUNDANT'},
                     'timeline': {'first_draft_line': min(prior['draft_write_lines']) if prior['draft_write_lines'] else None,
                     'first_draft_line_coverage': 'Visible file_change only; shell writes can lack a separate write event',
                     'last_validation_line': validation[-1]['line'] if validation else None, 'validation_events': validation,
                     'agent_completion_line': completed[-1] if completed else None, 'terminal_event_line': errors[-1][0] if errors else completed[-1] if completed else None,
                     'event_wall_clock': 'NOT_RECORDED', 'ledger_start_utc': start, 'ledger_end_utc': end, 'whole_target_elapsed_seconds': seconds},
                     'drafts': draft_states, 'usage': {k: usage.get(k) for k in ['status', 'input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens']},
                     'cost': {'command_count': prior['command_count'], 'output_characters': prior['output_chars'],
                     'output_utf8_bytes': sum(len(c.get('aggregated_output', '').encode()) for _, c in commands),
                     'wasted_tokens': None, 'missing_reason': 'No per-activity rollout accounting or counterfactual runtime'},
                     'root_cause_assessments': roots or [{'hypothesis': 'No fatal cause; successful localization quality needs separate analysis', 'confidence': 'NOT_APPLICABLE'}]})
    assert len(rows) == 90 and len({(x['task_id'], x['method']) for x in rows}) == 90
    output.mkdir(parents=True)
    doc = {'schema_version': 1, 'host_only': True, 'model_calls': 0, 'sources': sources, 'rows': rows,
           'termination_counts': dict(collections.Counter(r['direct_stop_reason'] for r in rows)),
           'limitations': ['Tool recovery matching is conservative and needs contextual review.', 'Missing event clocks do not permit per-action time estimates.', 'Draft hindsight metrics are host-only and never substitute for sealed scores.']}
    (output / 'diagnosis.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    with (output / 'diagnosis.csv').open('w', newline='') as stream:
        fields = ['task_id', 'method', 'state', 'direct_stop_reason', 'tool_errors', 'tool_recoveries', 'first_draft_line', 'last_validation_line', 'terminal_line', 'usage_status', 'known_total_tokens', 'elapsed_seconds', 'output_bytes', 'root_confidence']
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for r in rows:
            writer.writerow(dict(zip(fields, [r['task_id'], r['method'], r['state'], r['direct_stop_reason'], len(r['tools']),
                sum(x['recovery_line'] is not None for x in r['tools']), r['timeline']['first_draft_line'], r['timeline']['last_validation_line'], r['timeline']['terminal_event_line'],
                r['usage']['status'], r['usage']['total_tokens'], r['timeline']['whole_target_elapsed_seconds'], r['cost']['output_utf8_bytes'], r['root_cause_assessments'][0]['confidence']])))
    lines = ['# 首批30PR逐任务诊断（宿主机）', '', '耗费token按缺失保留，未按关键词将工具错误归因为致死原因。完整证据见diagnosis.json；CSV适合排序筛选。', '',
             '| PR | SDD | 终态 | 直接终止原因 | 工具错误/后续同工具成功 | 草稿/末次自检/终止行 | 用量状态 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        t = r['timeline']; lines.append(f"| {r['task_id'].split('pr')[-1]} | {r['method']} | {r['state']} | {r['direct_stop_reason']} | {len(r['tools'])}/{sum(x['recovery_line'] is not None for x in r['tools'])} | {t['first_draft_line']}/{t['last_validation_line']}/{t['terminal_event_line']} | {r['usage']['status']} |")
    (output / 'diagnosis.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(doc['termination_counts']))
    return doc


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args(); diagnose(args.root, args.output)
