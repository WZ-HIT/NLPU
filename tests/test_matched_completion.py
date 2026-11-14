"""B/C scope, pilot reuse, dispatch stopping, and evaluation denominator checks."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sdd-bench/scrapy-sdd'))
from experiment.test_intention import matched_completion as full, matched_pilot as pilot


class Counts(unittest.TestCase):
    def test_no_positive_failures_are_not_correct_empty(self):
        rows = [{'state': 'DETECT_SEALED', 'status': 'OK', 'testcase': {'tp': 2, 'fp': 1, 'fn': 1}},
                {'state': 'DETECT_SEALED', 'status': 'NO_POSITIVE_GOLD', 'testcase': None,
                 'prediction': {'testcases': ['x'], 'invalid': ['bad']}},
                {'state': 'DETECT_SEALED', 'status': 'NO_POSITIVE_GOLD', 'testcase': None,
                 'prediction': {'testcases': [], 'invalid': []}},
                {'state': 'BLOCKED', 'status': 'NO_POSITIVE_GOLD', 'testcase': None,
                 'prediction': {'testcases': [], 'invalid': []}}]
        result = full.all_task_counts(rows)
        self.assertEqual((result['tp'], result['fp'], result['fn']), (2, 3, 1))
        self.assertEqual(result['no_positive'], {'false_alarm': 1, 'correct_empty': 1, 'failed': 1})
        self.assertEqual(result['completed'], 3)

    def test_bootstrap_keeps_all_methods_in_a_pr_together(self):
        groups = {g: {'rows': []} for g in 'BC'}
        for task, delta in [('p1', 1.), ('p2', -1.)]:
            for method in full.METHODS:
                groups['B']['rows'].append({'task_id': task, 'method': method, 'testcase': {'recall': float(delta < 0)}})
                groups['C']['rows'].append({'task_id': task, 'method': method, 'testcase': {'recall': float(delta > 0)}})
        result = full.paired_bootstrap(groups, samples=100, seed=7)
        self.assertEqual(result['positive_prs'], 2)
        self.assertEqual(result['primary_delta'], 0)
        self.assertEqual(result['interval_95'], [-1., 1.])


class Controller(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name); self.root = self.output / 'execution-root'
        self.bench = self.root / 'sdd-bench/scrapy-sdd'
        (self.bench / 'schemas').mkdir(parents=True)
        shutil.copyfile(ROOT / 'sdd-bench/scrapy-sdd/schemas/batch-ledger-event-v1.schema.json', self.bench / 'schemas/batch-ledger-event-v1.schema.json')
        full.write(self.output / 'execution-lock.json', {})
        full.write(self.output / 'authorization.json', {'target_limit': 162, 'budget_policy': 'existing_balance_no_topup', 'groups': ['B', 'C']})
        full.write(self.output / 'offline-acceptance.json', {'status': 'PASS', 'execution_lock_sha256': full.first30.sha(self.output / 'execution-lock.json')})
        reused = {'source': 'immutable-pilot', 'groups': {g: [] for g in 'BC'}}
        self.plan = {'targets': []}; self.refs = {}; self.targets = {}
        for group in 'BC':
            directory = self.bench / 'batch/runs' / ('round-' + group.lower()*24); directory.mkdir(parents=True)
            self.refs[group] = {'manifest': str(directory / 'prepared-round.json'), 'prepared_id': directory.name}
        for pr in range(30):
            task = 'pr' + str(pr)
            for method in full.METHODS:
                for group in ('B', 'C') if pr % 2 else ('C', 'B'):
                    row = {'group': group, 'task_id': task, 'method': method, 'pilot': pr < 3}
                    self.plan['targets'].append(row)
                    if pr < 3:
                        reused['groups'][group].append({'task_id': task, 'method': method, 'target_key': task + ':' + method})
                    else:
                        target = {'task_id': task, 'method': method, 'run_id': 'detect-001', 'mode': None, 'stage': 'detect',
                                  'task_manifest': Path(self.refs[group]['manifest']).parent / 'tasks' / task / 'task.json'}
                        self.targets[(group, task, method)] = ({'batch_id': self.refs[group]['prepared_id']}, target)
        full.write(self.output / 'reused-rows.json', reused)

    def invoke(self, fake):
        with patch.object(full, 'prepared', return_value=(self.plan, self.refs, self.targets)), \
             patch.object(full, 'check'), \
             patch.object(full.first30, 'execution_environment', return_value=(self.root, self.bench)), \
             patch('batch.stages.detect_targets', side_effect=fake), redirect_stdout(io.StringIO()):
            full.run(self.output)

    def test_reuses_18_and_runs_exactly_162_once_without_A(self):
        calls = []
        def fake(**args):
            calls.append(args['output']); return {'status': 'SEALED'}
        self.invoke(fake)
        self.assertEqual(len(calls), 162)
        self.assertTrue(all('/pr0/' not in str(p) and '/pr1/' not in str(p) and '/pr2/' not in str(p) for p in calls))
        status = full.status(self.output)
        self.assertEqual((status['reused'], status['new_formal_starts'], status['terminal']), (18, 162, 180))
        self.invoke(fake)
        self.assertEqual(len(calls), 162)

    def test_balance_refusal_stops_and_never_retries_started(self):
        calls = []
        def fake(**args):
            calls.append(args['output']); args['output'].mkdir(parents=True)
            (args['output'] / 'agent.stderr.log').write_text('INSUFFICIENT BALANCE')
            raise ValueError('provider error')
        self.invoke(fake)
        self.assertLessEqual(len(calls), 3)
        self.assertEqual(full.status(self.output)['terminal'], 180)
        self.invoke(fake)
        self.assertEqual(full.status(self.output)['new_formal_starts'], len(calls))

    def test_interrupted_start_refuses_automatic_retry(self):
        journal = pilot.Journal(self.output / 'ledger.sqlite3')
        journal.start(pilot.key(next(r for r in self.plan['targets'] if not r['pilot'])))
        with self.assertRaisesRegex(ValueError, 'Interrupted'):
            self.invoke(lambda **kw: self.fail('must not call'))

    def test_scope_authorization_gate(self):
        full.write(self.output / 'authorization.json', {'target_limit': 243, 'budget_policy': 'existing_balance_no_topup', 'groups': ['A', 'B', 'C']})
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.invoke(lambda **kw: self.fail('must not call'))

    def test_reused_outcome_cannot_be_replaced(self):
        journal = pilot.Journal(self.output / 'ledger.sqlite3')
        reused = full.read(self.output / 'reused-rows.json'); full.seed_reused(journal, reused)
        reused['groups']['B'][0]['target_key'] = 'different'
        with self.assertRaisesRegex(ValueError, 'Reused outcome'):
            full.seed_reused(journal, reused)

    def test_scoring_cannot_start_with_incomplete_terminal_barrier(self):
        full.write(self.output / 'terminal.json', {'targets': {}})
        with patch.object(full, 'prepared', return_value=(self.plan, self.refs, self.targets)):
            with self.assertRaisesRegex(ValueError, '180'):
                full.compare(self.output)

    def test_complete_workflow_report_reuses_rows_and_keeps_cost_unknown(self):
        metric = {'tp': 1, 'fp': 0, 'fn': 0, 'predicted_count': 1, 'gold_count': 1,
                  'invalid_count': 0, 'precision': 1., 'recall': 1., 'f1': 1.}
        def scored(row):
            return {'task_id': row['task_id'], 'method': row['method'], 'state': 'DETECT_SEALED',
                    'status': 'OK', 'testcase': dict(metric), 'scoped_file': dict(metric),
                    'legacy_file': dict(metric), 'index_sha256': 'same-index', 'labels_sha256': 'same-labels',
                    'prediction': {'testcases': ['x'], 'invalid': []}}
        reused = full.read(self.output / 'reused-rows.json')
        for group in 'BC':
            reused['groups'][group] = [dict(r, **scored(r)) for r in reused['groups'][group]]
        full.write(self.output / 'reused-rows.json', reused)
        self.plan.update(bootstrap={'samples': 20, 'seed': 7}, scope_revision='B/C only')
        self.invoke(lambda **kw: {'status': 'SEALED'})
        full.write(self.output / 'pilot-closeout.json', {'rows': [{'group': g, 'usage': None} for g in 'BC' for _ in range(9)]})
        documents = {ref['prepared_id']: {'batch_id': ref['prepared_id'],
                     'rows': [scored(r) for r in self.plan['targets'] if not r['pilot'] and r['group'] == group],
                     'tasks': {r['task_id']: {'labels': {'testcases': ['x']}} for r in self.plan['targets'] if not r['pilot']}}
                     for group, ref in self.refs.items()}
        with patch.object(full, 'prepared', return_value=(self.plan, self.refs, self.targets)), \
             patch.object(full.first30, 'execution_environment', return_value=(self.root, self.bench)), \
             patch('batch.testcase_metrics.compute', side_effect=lambda bench, group: documents[group]), \
             patch('batch.testcase_metrics.validate'), \
             patch.object(full, 'log_audit', return_value={'usage': None}):
            full.compare(self.output)
        report = full.read(self.output / 'host-comparison/paired.json')
        self.assertEqual(len(report['groups']['B']['rows']), 90)
        self.assertEqual(report['groups']['C']['all_task_micro']['tp'], 90)
        self.assertIsNone(report['cost']['actual_currency'])
        self.assertEqual(report['usage']['B']['combined']['missing'], 90)
        self.assertEqual(report['primary_analysis']['primary_delta'], 0)
        self.assertEqual(full.read(self.output / 'completion.json')['status'], 'COMPLETE')


if __name__ == '__main__':
    unittest.main()
