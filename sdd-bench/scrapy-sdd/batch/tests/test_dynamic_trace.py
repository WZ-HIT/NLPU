"""Offline trace-bundle boundaries; no repository tests or model calls."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from batch.core import BatchError, sha256_file
from batch.dynamic_trace import binding, bundles, prompt, verify_bundle, verify_reuse, verify_source_snapshot, verify_workspace
from batch.prepare import _validate

BASE = 'a' * 40
METHODS = ('openspec', 'speckit', 'cc-sdd')


def make_bundle(root):
    root.mkdir(parents=True)
    for name, content in {'README.md': 'Frozen coverage', 'query.py': 'import json\n',
                          'index.json': '{}', 'symbols.json': '{}',
                          'methods/test-a.json': '{"status":"passed"}',
                          'instances/test-a.json': '{"status":"passed"}',
                          'indexes/reverse.json': '{}'}.items():
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content)
    manifest = {'schema_version': 1, 'document_type': 'TEST_TRACE_BUNDLE',
                'base_sha': BASE, 'snapshot_id': 'source-a', 'environment_id': 'env-a',
                'files': {p.relative_to(root).as_posix(): sha256_file(p)
                          for p in root.rglob('*') if p.is_file()}}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return root


class DynamicTraceTests(unittest.TestCase):
    def test_recorded_source_bytes_and_executable_bits_must_match_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = make_bundle(root / 'bundle')
            baseline = root / 'baseline'; baseline.mkdir()
            source = baseline / 'module.py'; source.write_text('def run(): return 1\n')
            source.chmod(0o644)
            manifest_path = package / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['source_files'] = {'module.py': sha256_file(source)}
            manifest['source_executable_bits'] = {'module.py': 0}
            manifest_path.write_text(json.dumps(manifest))
            verify_source_snapshot(package, baseline)
            source.write_text('def run(): return 2\n')
            with self.assertRaises(BatchError) as caught:
                verify_source_snapshot(package, baseline)
            self.assertEqual(caught.exception.code, 'TRACE_SOURCE_MISMATCH')
            source.write_text('def run(): return 1\n')
            source.chmod(0o755)
            with self.assertRaises(BatchError):
                verify_source_snapshot(package, baseline)
            source.chmod(0o644)
            source.unlink()
            outside = root / 'outside.py'; outside.write_text('def run(): return 1\n')
            source.symlink_to(outside)
            with self.assertRaises(BatchError):
                verify_source_snapshot(package, baseline)

    def test_fake_round_compiles_trace_binding_for_all_three_methods(self):
        from batch.rounds import compile_round
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = make_bundle(root / 'bundle')
            def document(name, value):
                path = root / name; path.write_text(json.dumps(value))
                return {'path': name, 'sha256': sha256_file(path)}
            public = document('task.json', {'task_id': 'scrapy__scrapy__pr1',
                                          'baseline': {'base_sha': BASE}})
            plan = document('plan.json', {'tasks': [{'task_id': 'scrapy__scrapy__pr1',
                                                     'baseline': {'base_sha': BASE}}]})
            report = document('provision.json', {})
            source_ref = document('source.json', {})
            source = {'approved_plan': {'path': plan['path'], 'sha256': plan['sha256'],
                                       'provision_report_path': report['path'],
                                       'provision_report_sha256': report['sha256'], 'plan_id': 'fake'},
                      'tasks': [{'task_id': 'scrapy__scrapy__pr1', 'task_manifest': public,
                                 'methods': [{'method': method, 'detect': {'run_id': 'detect-001'}}
                                             for method in METHODS]}]}
            config = {'schema_version': 2, 'experiment_id': 'fake-trace', 'prs': [1],
                      'methods': list(METHODS), 'stages': ['detect'], 'update_modes': [],
                      'evaluation': {'kind': 'detect-host'}, 'sources': [source_ref],
                      'dynamic_trace': {'entrypoint': 'test-traces/README.md', 'artifacts': {BASE: {
                          'path': 'bundle/manifest.json', 'sha256': sha256_file(package / 'manifest.json')}}}}
            document('config.json', config)
            with patch('batch.rounds.validate_batch_config', return_value=(source, None)), \
                 patch('batch.rounds.validate_plan_inputs', return_value={'valid': True}), \
                 patch('batch.rounds._image_record', return_value={'base_sha': BASE}):
                compiled = compile_round(root / 'config.json', 'trace-001', root=root)
            self.assertEqual(compiled['dynamic_traces'], {BASE: package})
            self.assertEqual(compiled['test_intentions'], {})
            self.assertEqual({target['method'] for target in compiled['targets']}, set(METHODS))
            self.assertEqual(len(compiled['targets']), 3)

    def test_configuration_is_optional_exactly_base_scoped_and_composable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = make_bundle(root / 'bundle')
            ref = {'path': 'bundle/manifest.json', 'sha256': sha256_file(package / 'manifest.json')}
            enhancement = {'entrypoint': 'test-traces/README.md', 'artifacts': {BASE: ref}}
            config = {'schema_version': 2, 'experiment_id': 'trace-check', 'prs': [1],
                      'methods': list(METHODS), 'stages': ['detect'], 'update_modes': [],
                      'evaluation': {'kind': 'detect-host', 'localization_protocol': 'testcase-v1'},
                      'sources': [ref], 'dynamic_trace': enhancement,
                      'test_intention': {'entrypoint': 'test-intentions/README.md', 'artifacts': {BASE: ref}}}
            _validate(config, 'experiment-config-v2.schema.json')
            self.assertEqual(bundles({}, root, {BASE}), {})
            self.assertEqual(bundles(config, root, {BASE}), {BASE: package})
            with self.assertRaises(BatchError):
                bundles(config, root, {BASE, 'b' * 40})
            bad = copy.deepcopy(config)
            bad['dynamic_trace']['artifacts'][BASE]['path'] = '/host/manifest.json'
            with self.assertRaises(BatchError):
                _validate(bad, 'experiment-config-v2.schema.json')
            (package / 'query.py').write_text('changed')
            with self.assertRaises(BatchError):
                bundles(config, root, {BASE})

    def test_symlinks_extra_files_diagnostics_and_escaping_paths_rejected(self):
        for kind in ('symlink', 'unlisted', 'diagnostic', 'escaping', 'missing'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                package = make_bundle(root / 'bundle')
                manifest_path = package / 'manifest.json'
                manifest = json.loads(manifest_path.read_text())
                if kind == 'symlink':
                    (package / 'outside').symlink_to(root, target_is_directory=True)
                elif kind == 'unlisted':
                    (package / 'unknown.json').write_text('{}')
                elif kind == 'diagnostic':
                    (package / 'diagnostics').mkdir()
                    path = package / 'diagnostics/failed.json'
                    path.write_text('{}')
                    manifest['files']['diagnostics/failed.json'] = sha256_file(path)
                elif kind == 'escaping':
                    manifest['files']['../outside.json'] = 'a' * 64
                else:
                    (package / 'query.py').unlink()
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaises(BatchError):
                    verify_bundle(manifest_path, BASE)

    def test_three_workspaces_share_bytes_and_reuse_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = make_bundle(root / 'bundle')
            task = root / 'task'; task.mkdir()
            (task / 'dynamic-trace.json').write_text(json.dumps(binding(package, BASE)))
            for method in METHODS:
                workspace = task / 'runs' / method / 'detect/workspace'
                shutil.copytree(package, workspace / 'test-traces')
                verify_workspace(task, workspace, BASE)
            verify_reuse(task, BASE, package, METHODS)
            with self.assertRaises(BatchError):
                verify_reuse(task, BASE, None, METHODS)
            target = task / 'runs/speckit/detect/workspace/test-traces/query.py'
            target.write_text('modified')
            with self.assertRaises(BatchError):
                verify_reuse(task, BASE, package, METHODS)
            target.write_bytes((package / 'query.py').read_bytes())
            sidecar = task / 'dynamic-trace.json'
            document = json.loads(sidecar.read_text()); document['manifest_sha256'] = '0' * 64
            sidecar.write_text(json.dumps(document))
            with self.assertRaises(BatchError):
                verify_reuse(task, BASE, package, METHODS)

    def test_trace_only_detect_checks_frozen_workspace_before_any_agent_call(self):
        from batch.stages import detect_targets
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); task = root / 'task'; task.mkdir()
            task_manifest = task / 'task.json'
            task_manifest.write_text('{}')
            workspace = task / 'runs/openspec/detect/workspace'
            package = make_bundle(workspace / 'test-traces')
            (task / 'dynamic-trace.json').write_text(json.dumps(binding(package, BASE)))
            public = {'baseline': {'base_sha': BASE}}
            output = task / 'runs/openspec/detect/executions/check-001'
            with patch('batch.stages._task_context', return_value=(public, task, BASE)), \
                 patch('batch.stages._preflight_ready'), \
                 patch('batch.stages._verify_initial_detect_workspace', side_effect=BatchError('FROZEN_CHANGED', 'changed')) as check, \
                 patch('batch.stages._run_compose_agent') as agent:
                with self.assertRaises(BatchError) as caught:
                    detect_targets(task_manifest=task_manifest, method='openspec', run_id='check-001',
                                   output=output, bench=root, repository_root=root, dry_run=False,
                                   localization_protocol='testcase-v1')
                self.assertEqual(caught.exception.code, 'FROZEN_CHANGED')
                check.assert_called_once_with(task, 'openspec', workspace)
                agent.assert_not_called()
            self.assertIn('All existing tests remain searchable', prompt())


if __name__ == '__main__':
    unittest.main()
