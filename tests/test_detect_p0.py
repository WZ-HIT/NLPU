"""P0 regressions: public contract, interruptions, preserved scoring and prompts."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / 'sdd-bench/scrapy-sdd'
sys.path.insert(0, str(BENCH))
from batch.public_detect import contract
from batch.scaffold import METHODS
from batch.stages import detect_prompt, _codex_catalog_override
from batch.testcase_identity import inventory, resolve


class DetectP0Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'; (self.repo / 'tests').mkdir(parents=True)
        self.source = self.repo / 'tests/test_sample.py'
        self.source.write_text('''import does_not_exist
class Outer:
    class Inner:
        async def test_case(self):
            assert True
@pytest.fixture
def test_fixture(): pass
def helper(): pass
''')
        self.planning = self.root / 'planning'; self.planning.mkdir()
        self.draft = {'candidates': [{'path': 'tests/test_sample.py', 'symbols': ['Outer.Inner.test_case'], 'reason': 'Explicit task requires changing the base assertion'}]}

    def test_root_array_and_stable_field_errors(self):
        self.assertEqual(contract.structure([])[0]['code'], 'DRAFT_ROOT_TYPE')
        self.assertEqual(contract.structure([])[0]['field'], '$')
        bad = {'candidates': [{'path': None, 'symbols': None, 'reason': None}]}
        self.assertEqual({e['field'] for e in contract.structure(bad)}, {'candidates[0].path', 'candidates[0].symbols', 'candidates[0].reason'})
        for value in [None, 1, 'wrong', {}, {'candidates': {}}, {'candidates': [None]}]:
            self.assertFalse(contract.validate(value, self.repo)['structure_valid'])

    def test_valid_empty_and_protocol_symbol_cardinality(self):
        self.assertEqual(contract.validate({'candidates': []}, self.repo)['errors'], [])
        empty = {'candidates': [{'path': 'tests/test_sample.py', 'symbols': [], 'reason': 'File-level task'}]}
        self.assertFalse(contract.validate(empty, self.repo)['structure_valid'])
        self.assertTrue(contract.validate(empty, self.repo, 'file-v1')['structure_valid'])

    def test_identity_is_exact_nested_source_and_never_imports_project(self):
        self.assertTrue(contract.validate(self.draft, self.repo)['identity_valid'])
        for name in ['test_case', 'Outer.test_case', 'helper', 'test_fixture']:
            value = {'candidates': [{**self.draft['candidates'][0], 'symbols': [name]}]}
            result = contract.validate(value, self.repo)
            self.assertTrue(result['structure_valid']); self.assertFalse(result['identity_valid'])
            self.assertEqual(result['errors'][0]['code'], 'SOURCE_TEST_NOT_FOUND')

    def test_duplicate_definition_is_ambiguous(self):
        self.source.write_text('def test_x(): pass\ndef test_x(): pass\n')
        value = {'candidates': [{**self.draft['candidates'][0], 'symbols': ['test_x']}]}
        self.assertEqual(contract.validate(value, self.repo)['errors'][0]['code'], 'SOURCE_TEST_AMBIGUOUS')

    def test_source_symlink_and_escape_are_rejected(self):
        for path in ['../tests/test.py', 'tests/../../secret.py', '/tmp/test.py', 'tests\\test.py']:
            value = {'candidates': [{**self.draft['candidates'][0], 'path': path}]}
            self.assertFalse(contract.validate(value, self.repo)['structure_valid'])
        self.source.unlink(); self.source.symlink_to(self.root / 'outside.py')
        result = contract.validate(self.draft, self.repo)
        self.assertTrue(result['structure_valid']); self.assertFalse(result['identity_valid'])

    def test_invalid_id_diagnostics_preserve_false_positive_prediction(self):
        self.draft['candidates'][0]['symbols'].append('Missing.test_method')
        checked = contract.validate(self.draft, self.repo)
        self.assertTrue(checked['structure_valid']); self.assertFalse(checked['identity_valid'])
        index = inventory(self.repo, 'a' * 40)
        resolved = resolve(self.draft['candidates'], index)
        self.assertEqual(resolved['invalid'], ['tests/test_sample.py::Missing.test_method'])
        self.assertEqual(len(self.draft['candidates'][0]['symbols']), 2)

    def test_public_cli_and_host_use_identical_copied_code(self):
        public = self.root / 'public'; public.mkdir()
        for name in ['contract.py', 'draft.schema.json']:
            shutil.copyfile(BENCH / 'batch/public_detect' / name, public / name)
        draft = self.root / 'input.json'; draft.write_text(json.dumps(self.draft))
        result = subprocess.run([sys.executable, str(public / 'contract.py'), 'validate', '--repository', str(self.repo), '--file', str(draft)], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), contract.validate(self.draft, self.repo))

    def test_shared_schema_agrees_on_structure_examples(self):
        from jsonschema import Draft202012Validator
        schema = Draft202012Validator(json.loads((BENCH / 'batch/public_detect/draft.schema.json').read_text()))
        for value in [[], {}, {'candidates': []}, self.draft, {'candidates': [None]}, {'candidates': [{'path': 'tests/test.py', 'symbols': [42], 'reason': 'x'}]}]:
            self.assertEqual(schema.is_valid(value), contract.validate(value)['structure_valid'])

    def test_partial_draft_is_not_formal_and_can_be_revised(self):
        contract.save_draft(self.planning, {'candidates': []}, ['Need to inspect inheritance'])
        self.assertEqual(contract.finalize(self.planning, self.repo)['status'], 'PENDING_ITEMS')
        self.assertFalse((self.planning / 'detection-draft.json').exists())
        contract.save_draft(self.planning, self.draft, [])
        self.assertEqual(contract.finalize(self.planning, self.repo)['status'], 'PUBLISHED')
        self.assertEqual(json.loads((self.planning / 'detection-draft.json').read_text()), self.draft)
        contract.save_draft(self.planning, {'candidates': []}, ['Further review'])
        self.assertEqual(json.loads(contract.progress_file(self.planning).read_text())['phase'], 'INVESTIGATING')

    def test_interrupted_atomic_replace_keeps_last_complete_json(self):
        path = self.planning / 'progress.json'
        contract.atomic_json(path, {'old': True})
        with patch.object(contract.os, 'replace', side_effect=InterruptedError('simulated exit')):
            with self.assertRaises(InterruptedError): contract.atomic_json(path, {'new': True})
        self.assertEqual(json.loads(path.read_text()), {'old': True})
        self.assertEqual(list(self.planning.iterdir()), [path])

    def test_validation_failure_and_repair_limit_preserve_provisional_state(self):
        for i in range(contract.MAX_VALIDATIONS):
            contract.save_draft(self.planning, {'revision': i}, [])
            self.assertEqual(contract.finalize(self.planning, self.repo)['status'], 'VALIDATION_FAILED')
        contract.save_draft(self.planning, self.draft, [])
        self.assertEqual(contract.finalize(self.planning, self.repo)['status'], 'VALIDATION_LIMIT')
        self.assertFalse((self.planning / 'detection-draft.json').exists())

    def test_unchanged_validation_is_cached_and_source_rechecked(self):
        contract.save_draft(self.planning, self.draft, [])
        for _ in range(5): self.assertEqual(contract.finalize(self.planning, self.repo)['status'], 'PUBLISHED')
        state = json.loads(contract.progress_file(self.planning).read_text())
        self.assertEqual(state['validation_count'], 1)
        self.source.write_text('def helper(): pass\n')
        self.assertEqual(contract.finalize(self.planning, self.repo)['status'], 'BASE_CHANGED')

    def test_timeout_tool_error_and_budget_reminder_do_not_auto_publish(self):
        # Kill a real helper process after it has durably saved a provisional
        # draft. No model or repository tests run in the child.
        script = ("import sys,time; sys.path.insert(0,sys.argv[1]); import contract; "
                  "contract.save_draft(sys.argv[2], {'candidates': []}, ['Tool check pending']); "
                  "print('SAVED',flush=True); time.sleep(30)")
        child = subprocess.Popen([sys.executable, '-c', script, str(BENCH / 'batch/public_detect'), str(self.planning)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'SAVED')
            child.terminate(); child.wait(timeout=3)
        finally:
            if child.poll() is None: child.kill(); child.wait()
            child.stdout.close()
        self.assertEqual(json.loads(contract.progress_file(self.planning).read_text())['phase'], 'INVESTIGATING')
        self.assertFalse((self.planning / 'detection-draft.json').exists())
        status = contract.reserve_status(deadline=100, now=99)
        self.assertTrue(status['start_finalizing']); self.assertFalse(status['automatic_publish'])
        self.assertIsNone(status['remaining_rollout_tokens'])
        self.assertTrue(contract.reserve_status(remaining_tokens=1000)['start_finalizing'])
        self.assertFalse(contract.reserve_status(deadline=1000, now=1)['start_finalizing'])

    def test_host_returns_root_error_instead_of_unhashable_exception(self):
        from batch.core import BatchError
        from batch import stages
        task = self.root / 'task'
        workspace = task / 'runs/openspec/detect/workspace'
        workspace.mkdir(parents=True)
        planning = task / 'runs/openspec/detect/planning-artifacts'; planning.mkdir()
        manifest = task / 'task.json'; manifest.write_text('{}')
        output = task / 'runs/openspec/detect/executions/run-1/attempt-1'
        def fake_agent(**kwargs):
            (planning / 'detection-draft.json').write_text(json.dumps(self.draft['candidates']))
            return 'a' * 64, 'b' * 64
        with patch.object(stages, '_task_context', return_value=({'task_id': 'task', 'baseline': {'base_sha': 'a' * 40}}, task, 'a' * 40)), patch.object(stages, '_preflight_ready'), patch.object(stages, '_run_compose_agent', side_effect=fake_agent):
            with self.assertRaises(BatchError) as caught:
                stages.detect_targets(task_manifest=manifest, method='openspec', run_id='run-1', output=output, bench=BENCH, repository_root=self.root, dry_run=False, localization_protocol='testcase-v1')
        self.assertEqual(caught.exception.code, 'INVALID_DETECTION_DRAFT')
        self.assertEqual(json.loads((output / 'draft-validation.json').read_text())['errors'][0]['code'], 'DRAFT_ROOT_TYPE')

    def test_host_refuses_to_seal_a_revised_but_unfinished_progress_draft(self):
        from batch.core import BatchError
        from batch import stages
        task = self.root / 'task'
        workspace = task / 'runs/openspec/detect/workspace'; workspace.mkdir(parents=True)
        planning = task / 'runs/openspec/detect/planning-artifacts'; planning.mkdir()
        manifest = task / 'task.json'; manifest.write_text('{}')
        output = task / 'runs/openspec/detect/executions/run-1/attempt-1'
        def fake_agent(**kwargs):
            (planning / 'detection-draft.json').write_text('{"candidates": []}')
            contract.save_draft(planning, {'candidates': []}, ['Review incomplete'])
            return 'a' * 64, 'b' * 64
        with patch.object(stages, '_task_context', return_value=({'task_id': 'task', 'baseline': {'base_sha': 'a' * 40}}, task, 'a' * 40)), patch.object(stages, '_preflight_ready'), patch.object(stages, '_run_compose_agent', side_effect=fake_agent):
            with self.assertRaises(BatchError) as caught:
                stages.detect_targets(task_manifest=manifest, method='openspec', run_id='run-1', output=output, bench=BENCH, repository_root=self.root, dry_run=False, localization_protocol='testcase-v1')
        self.assertEqual(caught.exception.code, 'DETECTION_PROGRESS_UNFINISHED')

    def test_all_method_prompts_have_explicit_paths_and_paired_rules(self):
        for method, settings in METHODS.items():
            prompt = detect_prompt(method, 'testcase-v1')
            self.assertIn(settings['planning_mount_path'] + '/detection-draft.json', prompt)
            self.assertIn('Prediction rule:', prompt); self.assertIn('Identity/scoring rule:', prompt)
            self.assertIn('180 seconds', prompt); self.assertIn('shared helper suffices', prompt)
            self.assertIn(', '.join(settings['detect_phases']), prompt)
        self.assertNotIn('Prediction rule:', detect_prompt('openspec', 'file-v1'))

    def test_label_boundary_distinguishes_ast_equal_and_equivalent_rewrites(self):
        from batch.testcase_labels import build_labels
        old = 'def test_x():\n    assert 1 == 1\n'
        self.source.write_text(old)
        index = inventory(self.repo, 'a' * 40)
        def labels(new):
            return build_labels({'base_sha': 'a' * 40, 'test_changes': [{'file': 'tests/test_sample.py', 'qualified_name': 'test_x', 'change_type': 'modified', 'old_test': old, 'gold_test': new}]}, index)
        formatting = labels('def test_x( ):\n    # comment\n    assert (1 == 1)\n')
        equivalent = labels('def test_x():\n    assert True\n')
        self.assertEqual(formatting['testcases'], [])
        self.assertEqual(formatting['excluded_counts'], {'mechanical_ast_equal': 1})
        self.assertEqual(equivalent['testcases'], ['tests/test_sample.py::test_x'])

    def test_runtime_override_mount_is_public_only_and_read_only(self):
        import yaml
        value = yaml.safe_load(_codex_catalog_override('openspec', 'detect', Path('/runtime'), Path('/private-snapshot')))
        service = value['services']['openspec-detect-agent']
        public = next(v for v in service['volumes'] if v['target'] == '/run/sdd-public')
        self.assertTrue(public['read_only']); self.assertEqual(public['source'], '/private-snapshot')
        self.assertEqual(service['environment']['BASH_ENV'], '/run/sdd-public/shell-env.sh')

    def test_launcher_explicitly_sets_public_environment_through_core_filter(self):
        from batch.stages import _formal_launch
        import tomllib
        fragment = 'codex exec' + _formal_launch().split('codex exec', 1)[1]
        # Substitute only a shell function that prints argv; no Codex process.
        command = "codex() { printf '%s\\n' \"$@\"; }; " + fragment
        process = subprocess.run(['/bin/sh', '-c', command], env={'SDD_DETECT_DEADLINE_EPOCH': '123456'}, capture_output=True, text=True, check=True)
        argv = process.stdout.splitlines()
        configs = [tomllib.loads(argv[i + 1]) for i, arg in enumerate(argv) if arg == '-c']
        self.assertEqual(configs[0]['shell_environment_policy']['set']['BASH_ENV'], '/run/sdd-public/shell-env.sh')
        self.assertEqual(configs[1]['shell_environment_policy']['set']['SDD_DETECT_DEADLINE_EPOCH'], '123456')

    def test_public_bootstrap_does_not_change_update_environment(self):
        from batch.stages import _formal_launch
        from batch.compose_preflight import _environment
        self.assertNotIn('shell_environment_policy.set', _formal_launch(False))
        self.assertNotIn('BASH_ENV', _environment('openspec', 'update', 'run-1'))
        self.assertIn('BASH_ENV', _environment('openspec', 'detect', 'run-1'))


if __name__ == '__main__':
    unittest.main()
