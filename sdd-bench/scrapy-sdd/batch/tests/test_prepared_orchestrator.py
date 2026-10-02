"""Prepared-target orchestration with a fake Agent/stage boundary."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from batch.core import BatchError
from batch.orchestrator import orchestrate, target_key
from batch.stages import enforce_update_scope

REPO = Path(__file__).resolve().parents[4]
REAL_BENCH = REPO / 'sdd-bench/scrapy-sdd'


class PreparedOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=REPO)
        self.root = Path(self.temp.name)
        self.bench = self.root / 'sdd-bench/scrapy-sdd'
        (self.bench / 'schemas').mkdir(parents=True)
        (self.bench / 'schemas/batch-ledger-event-v1.schema.json').write_bytes(
            (REAL_BENCH / 'schemas/batch-ledger-event-v1.schema.json').read_bytes())
        self.task = self.bench / 'tasks/task-pr1/task.json'
        self.task.parent.mkdir(parents=True)
        self.task.write_text(json.dumps({'task_id': 'task-pr1', 'baseline': {'base_sha': 'a' * 40}}))
        self.sealed = self.task.parent / 'sealed-policy.json'
        self.directed = self.task.parent / 'directed-policy.json'
        self.sealed.write_text('{}'); self.directed.write_text('{}')
        self.manifest_path = self.root / 'prepared.json'
        self.manifest_path.write_text(json.dumps({'prepared_id': 'prepared-' + '1' * 24}))
        self.targets = [
            self.target('td', 'detect', None, 'detect-001', None),
            self.target('ts', 'update', 'sealed-detect', 'sealed-001', self.sealed),
            self.target('tu', 'update', 'self-directed', 'self-001', self.directed),
        ]
        self.config = {'batch_id': 'prepared-' + '1' * 24, 'prepared_id': 'prepared-' + '1' * 24,
                       'experiment_id': 'fake'}

    def tearDown(self):
        self.temp.cleanup()

    def target(self, suffix, stage, mode, run_id, policy):
        return {'target_id': 'target-' + suffix, 'task_id': 'task-pr1', 'task_manifest': self.task,
                'method': 'openspec', 'stage': stage, 'run_id': run_id, 'mode': mode,
                'policy': policy, 'policy_sha256': hashlib.sha256(b'{}').hexdigest() if policy else None}

    def invoke(self, command, **kwargs):
        defaults = dict(command=command, manifest_path=self.manifest_path, bench=self.bench,
                        repository_root=self.root, dry_run=False, resume=False, retries=set(),
                        task_ids=set(), methods=set(), modes=set(), recover_detects=set(), archive=False)
        defaults.update(kwargs)
        with patch('batch.orchestrator.validate_prepared_manifest', return_value=(self.config, self.targets)):
            return orchestrate(**defaults)

    def files(self):
        root = self.bench / 'batch/runs' / self.config['batch_id']
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}

    def test_barrier_modes_scope_retry_resume_and_inspect(self):
        calls = []
        def fake_detect(**kwargs):
            calls.append(('detect', kwargs['dry_run']))
            return {'status': 'SEALED'}
        def fake_update(**kwargs):
            calls.append((kwargs['policy_path'].name, kwargs['dry_run']))
            return {'status': 'SEALED'}
        def barrier(**kwargs):
            latest = kwargs['latest']
            self.assertEqual(latest[target_key(self.targets[0])]['state'], 'DETECT_SEALED')
            calls.append(('barrier', False))
            return {'barrier_sha256': 'b' * 64}
        with patch('batch.orchestrator.detect_targets', side_effect=fake_detect), \
             patch('batch.orchestrator.update_tests', side_effect=fake_update), \
             patch('batch.orchestrator._ensure_detect_barrier', side_effect=barrier):
            result = self.invoke('all')
        self.assertEqual(result['status'], 'READY')
        self.assertLess(calls.index(('detect', False)), calls.index(('barrier', False)))
        self.assertIn(('sealed-policy.json', False), calls)
        self.assertIn(('directed-policy.json', False), calls)
        self.assertTrue(all(row['target_id'] for row in result['results']))
        self.assertEqual(enforce_update_scope('sealed-detect', ['tests/a.py', 'src/a.py'], ['tests/a.py']), ['src/a.py'])
        self.assertEqual(enforce_update_scope('self-directed', ['tests/a.py', 'src/a.py'], []), ['src/a.py'])

        before = self.files()
        inspected = self.invoke('inspect')
        after = self.files()
        self.assertEqual(inspected['command'], 'inspect')
        self.assertEqual(before, after)

        with patch('batch.orchestrator.detect_targets', return_value={'status': 'DRY_RUN_READY'}), \
             patch('batch.orchestrator.update_tests', return_value={'status': 'DRY_RUN_READY'}):
            probed = self.invoke('probe')
        self.assertTrue(probed['dry_run'])
        self.assertGreater(len(self.files()), len(after))

        with patch('batch.orchestrator._ensure_detect_barrier', return_value={'barrier_sha256': 'b' * 64}):
            resumed = self.invoke('detect', resume=True)
        self.assertEqual(resumed['results'][0]['state'], 'SKIPPED_RESUME')

    def test_update_cannot_cross_incomplete_global_detect_barrier(self):
        with self.assertRaises(BatchError) as caught:
            self.invoke('update')
        self.assertEqual(caught.exception.code, 'DETECT_BARRIER_INCOMPLETE')
        run_root = self.bench / 'batch/runs' / self.config['batch_id']
        ledger = run_root / 'ledger.jsonl'
        self.assertFalse(ledger.exists())

    def test_partial_detect_success_does_not_claim_global_barrier(self):
        second = dict(self.targets[0], target_id='target-second', method='speckit', run_id='detect-002')
        with patch('batch.orchestrator.validate_prepared_manifest', return_value=(self.config, [self.targets[0], second])), \
             patch('batch.orchestrator.detect_targets', return_value={'status': 'SEALED'}), \
             patch('batch.orchestrator._ensure_detect_barrier') as barrier:
            result = orchestrate(command='detect', manifest_path=self.manifest_path, bench=self.bench,
                repository_root=self.root, dry_run=False, resume=False, retries=set(), task_ids=set(),
                methods={'openspec'}, modes=set(), recover_detects=set(), archive=False)
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['results'][0]['state'], 'DETECT_SEALED')
        barrier.assert_not_called()

    def test_interrupted_detect_can_start_a_new_attempt_without_overwriting(self):
        from batch.orchestrator import Ledger
        target = self.targets[0]
        run_root = self.bench / 'batch/runs' / self.config['batch_id']
        ledger = Ledger(run_root / 'ledger.jsonl', self.config['batch_id'],
                        self.bench / 'schemas/batch-ledger-event-v1.schema.json')
        for state in ('PLANNED', 'PREFLIGHT_READY', 'DETECT_RUNNING'):
            ledger.append('detect', target, state, 1, {'target': target_key(target)})
        previous = self.task.parent / 'runs/openspec/detect/executions/detect-001/attempt-1'
        previous.mkdir(parents=True)
        (previous / 'agent.stderr.log').write_text('interrupted before launch')
        def fake_detect(**kwargs):
            kwargs['output'].mkdir(parents=True)
            return {'status': 'SEALED'}
        with patch('batch.orchestrator.detect_targets', side_effect=fake_detect), \
             patch('batch.orchestrator._ensure_detect_barrier', return_value={'barrier_sha256': 'b' * 64}):
            result = self.invoke('detect', retries={target_key(target)}, task_ids={'task-pr1'})
        self.assertEqual(result['results'][0]['attempt'], 2)
        self.assertEqual(result['results'][0]['state'], 'DETECT_SEALED')
        self.assertEqual((previous / 'agent.stderr.log').read_text(), 'interrupted before launch')
        self.assertTrue((previous.parent / 'attempt-2').is_dir())

    def test_failed_target_requires_explicit_retry(self):
        only = [self.targets[0]]
        with patch('batch.orchestrator.validate_prepared_manifest', return_value=(self.config, only)), \
             patch('batch.orchestrator.detect_targets', side_effect=RuntimeError('fake Agent failed')):
            failed = orchestrate(command='detect', manifest_path=self.manifest_path, bench=self.bench,
                repository_root=self.root, dry_run=False, resume=False, retries=set(), task_ids=set(),
                methods=set(), modes=set(), recover_detects=set(), archive=False)
        self.assertEqual(failed['results'][0]['state'], 'FAILED')
        with self.assertRaises(BatchError):
            with patch('batch.orchestrator.validate_prepared_manifest', return_value=(self.config, only)):
                orchestrate(command='detect', manifest_path=self.manifest_path, bench=self.bench,
                    repository_root=self.root, dry_run=False, resume=False, retries=set(), task_ids=set(),
                    methods=set(), modes=set(), recover_detects=set(), archive=False)
        key = target_key(only[0])
        with patch('batch.orchestrator.validate_prepared_manifest', return_value=(self.config, only)), \
             patch('batch.orchestrator.detect_targets', return_value={'status': 'SEALED'}), \
             patch('batch.orchestrator._ensure_detect_barrier', return_value={'barrier_sha256': 'b' * 64}):
            retried = orchestrate(command='detect', manifest_path=self.manifest_path, bench=self.bench,
                repository_root=self.root, dry_run=False, resume=False, retries={key}, task_ids=set(),
                methods=set(), modes=set(), recover_detects=set(), archive=False)
        self.assertEqual(retried['results'][0]['attempt'], 2)
        self.assertEqual(retried['results'][0]['state'], 'DETECT_SEALED')


if __name__ == '__main__':
    unittest.main()
