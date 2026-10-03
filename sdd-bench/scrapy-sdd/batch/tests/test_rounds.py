"""Read-only multi-source round and frozen identity regression tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from batch.core import BatchError, canonical_sha256, sha256_file, write_json
from batch.prepare import _validate
from batch.rounds import compile_round, load_round

REPO = Path(__file__).resolve().parents[4]
BENCH = REPO / 'sdd-bench/scrapy-sdd'
CONFIG = BENCH / 'batch/experiments/scrapy-30pr-detect-rerun-v1.json'
SOURCES = ('scrapy-3pr-detect-v2', 'scrapy-10pr-detect-v3', 'scrapy-20pr-detect-v1')


class RoundTests(unittest.TestCase):
    def test_30_prs_expand_deterministically_to_historical_detect_targets(self) -> None:
        first = compile_round(CONFIG, 'rerun-001')
        second = compile_round(CONFIG, 'rerun-001')
        self.assertEqual(first['prepared_id'], second['prepared_id'])
        self.assertEqual(first['targets'], second['targets'])
        self.assertEqual((len(first['owners']), len(first['targets'])), (30, 90))
        expected = set()
        for name in SOURCES:
            source = json.loads((BENCH / 'batch/pilot' / (name + '.json')).read_text())
            for task in source['tasks']:
                for method in task['methods']:
                    expected.add((task['task_id'], method['method'], 'detect', None, method['detect']['run_id']))
        actual = {(t['task_id'], t['method'], t['stage'], t['mode'], t['run_id']) for t in first['targets']}
        self.assertEqual(actual, expected)
        self.assertNotEqual(first['prepared_id'], compile_round(CONFIG, 'rerun-002')['prepared_id'])
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            copied = Path(temp) / 'same-config.json'
            copied.write_bytes(CONFIG.read_bytes())
            self.assertEqual(first['prepared_id'], compile_round(copied, 'rerun-001')['prepared_id'])

    def test_duplicate_pr_and_stale_source_are_rejected(self) -> None:
        original = json.loads(CONFIG.read_text())
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            path = Path(temp) / 'config.json'
            duplicated = dict(original); duplicated['prs'] = [8064, 8064]
            write_json(path, duplicated)
            with self.assertRaises(BatchError) as error:
                compile_round(path, 'rerun-001')
            self.assertEqual(error.exception.code, 'PREPARE_DUPLICATE_PR')
            stale = dict(original); stale['sources'] = [dict(item) for item in original['sources']]
            stale['sources'][0]['sha256'] = '0' * 64
            write_json(path, stale)
            with self.assertRaises(BatchError) as error:
                compile_round(path, 'rerun-001')
            self.assertEqual(error.exception.code, 'PREPARE_INPUT_STALE')

    def test_config_snapshot_survives_working_config_edits(self) -> None:
        from batch.rounds import _freeze_config_snapshot
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp)
            config = root / 'working.json'
            config.write_text('{"prs":[1]}\n')
            digest = sha256_file(config)
            snapshot_ref = {'path': f'sdd-bench/scrapy-sdd/batch/round-configs/{digest}.json', 'sha256': digest}
            snapshot = _freeze_config_snapshot(config, snapshot_ref, root)
            config.write_text('{"prs":[2]}\n')
            self.assertEqual(sha256_file(snapshot), digest)
            self.assertEqual(_freeze_config_snapshot(config, snapshot_ref, root), snapshot)
            snapshot.write_text('tampered')
            with self.assertRaises(BatchError):
                _freeze_config_snapshot(config, snapshot_ref, root)

    def test_manifest_contract_and_round_task_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp)
            round_id = 'round-' + 'a' * 24
            run = root / 'sdd-bench/scrapy-sdd/batch/runs' / round_id
            task = run / 'tasks/task-pr1/task.json'
            task.parent.mkdir(parents=True)
            write_json(task, {'task_id': 'task-pr1', 'baseline': {'base_sha': 'a' * 40}})
            config = root / 'config.json'; write_json(config, {'schema_version': 2})
            source = root / 'source.json'; write_json(source, {})
            ref = lambda path: {'path': path.relative_to(root).as_posix(), 'sha256': sha256_file(path)}
            image = {'base_sha': 'a' * 40, 'baseline_lock': ref(source), 'deployment_lock': ref(source),
                     'agent': {'tag': 'test', 'image_id': 'sha256:' + 'a' * 64},
                     'baseline': {'tag': 'test', 'image_id': 'sha256:' + 'a' * 64}}
            identity = {'task_id': 'task-pr1', 'method': 'openspec', 'stage': 'detect', 'mode': None, 'run_id': 'detect-001'}
            target = {'target_id': 'target-' + canonical_sha256(identity)[:24], **identity,
                      'base_sha': 'a' * 40, 'task_manifest': ref(task), 'policy': None}
            compiled = {'prepared_id': round_id, 'config': {'experiment_id': 'test', 'evaluation': {'kind': 'detect-host'}},
                        'config_ref': ref(config), 'sources': [ref(source)], 'images': [image], 'targets': [target]}
            manifest = {'schema_version': 2, 'manifest_type': 'PREPARED_ROUND', 'experiment_id': 'test',
                        'round_label': 'rerun-001', 'prepared_id': round_id,
                        'inputs': {'user_config': ref(config), 'sources': [ref(source)], 'evaluation': {'kind': 'detect-host'}},
                        'images': [image], 'evidence': [ref(task)], 'target_count': 1, 'targets': [target]}
            path = run / 'prepared-round.json'; write_json(path, manifest)
            _validate(manifest, 'prepared-round-v2.schema.json')
            self.assertEqual(load_round(path, root=root, expected=compiled), manifest)
            bad = dict(manifest); bad['targets'] = [dict(target, task_manifest=ref(source))]
            write_json(path, bad)
            with self.assertRaises(BatchError) as error:
                load_round(path, root=root, expected=compiled)
            self.assertEqual(error.exception.code, 'ROUND_TASK_PATH_INVALID')


class RoundRunnerTests(unittest.TestCase):
    def test_fake_agent_round_ledger_and_read_only_inspect(self) -> None:
        from unittest.mock import patch
        from batch.orchestrator import orchestrate
        from batch.result_view import build, write
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp); bench = root / 'sdd-bench/scrapy-sdd'
            schemas = bench / 'schemas'; schemas.mkdir(parents=True)
            for name in ('batch-ledger-event-v1.schema.json', 'target-result-view-v2.schema.json'):
                (schemas / name).write_bytes((BENCH / 'schemas' / name).read_bytes())
            round_id = 'round-' + 'b' * 24
            run = bench / 'batch/runs' / round_id; run.mkdir(parents=True)
            path = run / 'prepared-round.json'; write_json(path, {'manifest_type': 'PREPARED_ROUND', 'prepared_id': round_id})
            task = run / 'tasks/task-pr1/task.json'; task.parent.mkdir(parents=True)
            write_json(task, {'task_id': 'task-pr1', 'pr_id': 1, 'title': 'Fake PR', 'baseline': {'base_sha': 'a' * 40}})
            identity = {'task_id': 'task-pr1', 'method': 'openspec', 'stage': 'detect', 'mode': None, 'run_id': 'detect-001'}
            manifest = {'manifest_type': 'PREPARED_ROUND', 'prepared_id': round_id, 'experiment_id': 'test',
                        'inputs': {'evaluation': {'kind': 'detect-host'}, 'sources': []},
                        'targets': [{'target_id': 'target-' + canonical_sha256(identity)[:24], **identity,
                                     'base_sha': 'a' * 40,
                                     'task_manifest': {'path': task.relative_to(root).as_posix(), 'sha256': sha256_file(task)},
                                     'policy': None}]}
            with patch('batch.rounds.load_round', return_value=manifest), \
                 patch('batch.orchestrator.detect_targets', return_value={'status': 'SEALED'}) as agent, \
                 patch('batch.orchestrator.validate_detection_prerequisite', return_value=({'seal': {'payload_sha256': 'a' * 64}}, task, sha256_file(task))):
                args = {'manifest_path': path, 'bench': bench, 'repository_root': root, 'dry_run': False,
                        'resume': False, 'retries': set(), 'task_ids': set(), 'methods': set(), 'modes': set(),
                        'archive': False}
                result = orchestrate(command='detect', **args)
                self.assertEqual(result['results'][0]['state'], 'DETECT_SEALED')
                self.assertEqual(agent.call_count, 1)
                view, _ = write(path, bench, root)
                self.assertEqual((view['schema_version'], view['counts']['detect_count']), (2, 1))
                before = (run / 'ledger.jsonl').read_bytes(), (run / 'result-view.json').read_bytes()
                inspected = orchestrate(command='inspect', **args)
                self.assertGreaterEqual(inspected['event_count'], 1)
                self.assertEqual(before, ((run / 'ledger.jsonl').read_bytes(), (run / 'result-view.json').read_bytes()))
                self.assertEqual(build(path, bench, root), view)
                (bench / "batch/pilot").mkdir()
                (bench / "tools").mkdir()
                (bench / "tools/sdd-results.py").write_bytes((BENCH / "tools/sdd-results.py").read_bytes())
                from batch.detect_metrics import compute
                metrics = compute(bench, round_id)
                self.assertEqual(metrics["counts"]["target_count"], 1)
                self.assertEqual(metrics["rows"][0]["target_key"], next(iter(view["targets"])))
                from batch.archive.viewer import module as viewer_module
                from batch.orchestrator import Ledger
                current_ledger = Ledger(run / "ledger.jsonl", round_id, schemas / "batch-ledger-event-v1.schema.json")
                current_ledger.append("detect", {**identity}, "SKIPPED_RESUME", 1, {"previous": "test"})
                view_before = (run / "result-view.json").read_bytes()
                loaded = viewer_module(bench)
                experiment = next(item for item in loaded.discover(bench) if item.batch_id == round_id and item.task_id_filter is None)
                self.assertEqual(len(loaded.batch_targets(experiment, bench)), 1)
                self.assertEqual((run / "result-view.json").read_bytes(), view_before)
                (bench / "Log/reports/round-archives" / round_id).mkdir(parents=True)
                with self.assertRaises(BatchError) as error:
                    orchestrate(command="probe", **args)
                self.assertEqual(error.exception.code, "ROUND_ARCHIVED")


class RoundArchiveTests(unittest.TestCase):
    def test_archive_is_separate_and_excludes_workspace_and_raw_gold(self) -> None:
        from unittest.mock import patch
        from batch.round_archive import archive_round, verify_archive
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp); bench = root / 'sdd-bench/scrapy-sdd'
            round_id = 'round-' + 'c' * 24
            run = bench / 'batch/runs' / round_id; run.mkdir(parents=True)
            path = run / 'prepared-round.json'; write_json(path, {'prepared_id': round_id})
            ledger = run / 'ledger.jsonl'; ledger.write_text('sealed event\n')
            view_path = run / 'result-view.json'; write_json(view_path, {'view_sha256': 'a' * 64})
            from batch.detect_metrics import document_path
            metric = document_path(bench, round_id); metric.parent.mkdir(parents=True); write_json(metric, {'status': 'OK'})
            final = run / 'final/report.json'; final.parent.mkdir(parents=True); write_json(final, {'status': 'READY'})
            workspace = run / 'tasks/pr1/runs/openspec/detect/workspace'
            workspace.mkdir(parents=True); (workspace / 'hidden.txt').write_text('workspace')
            gold = bench / 'batch/gold/pr1/gold-store.json'; gold.parent.mkdir(parents=True)
            gold.write_text('secret gold')
            prepared = {'prepared_id': round_id, 'evidence': [{'path': ledger.relative_to(root).as_posix(), 'sha256': sha256_file(ledger)}], 'target_count': 1}
            view = {'view_sha256': 'a' * 64, 'counts': {'target_count': 1, 'terminal_count': 1},
                    'targets': {'key': {'state': 'DETECT_SEALED'}}}
            with patch('batch.round_archive.load_round', return_value=prepared), patch('batch.round_archive.load_view', return_value=view):
                archived = archive_round(path, root=root)
            self.assertEqual(archived, verify_archive(bench / 'Log/reports/round-archives' / round_id))
            names = [item['path'] for item in archived['files']]
            self.assertTrue(any(name.endswith('ledger.jsonl') for name in names))
            self.assertFalse(any('workspace' in name or '/gold/' in name for name in names))


class RoundPrepareTests(unittest.TestCase):
    def test_interrupted_prepare_resumes_and_detects_hash_conflict(self) -> None:
        from unittest.mock import patch
        from batch.prepare import _target
        from batch.rounds import prepare_round
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp); bench = root / 'sdd-bench/scrapy-sdd'
            source = root / 'source.json'; write_json(source, {})
            plan = root / 'plan.json'; write_json(plan, {})
            report = root / 'report.json'; write_json(report, {})
            config = root / 'config.json'; write_json(config, {'schema_version': 2})
            ref = lambda path: {'path': path.relative_to(root).as_posix(), 'sha256': sha256_file(path)}
            round_id = 'round-' + 'd' * 24
            task_id = 'scrapy__scrapy__pr1'
            run = bench / 'batch/runs' / round_id
            target_path = run / 'tasks' / task_id / 'task.json'
            public = {'task_id': task_id, 'baseline': {'base_sha': 'a' * 40}}
            source_task_path = root / 'original-task.json'; write_json(source_task_path, public)
            original = ref(source_task_path)
            image = {'base_sha': 'a' * 40, 'baseline_lock': ref(source), 'deployment_lock': ref(source),
                     'agent': {'tag': 'test', 'image_id': 'sha256:' + 'a' * 64},
                     'baseline': {'tag': 'test', 'image_id': 'sha256:' + 'a' * 64}}
            compiled = {'config': {'experiment_id': 'test', 'evaluation': {'kind': 'detect-host'}},
                        'config_ref': ref(config), 'prepared_id': round_id, 'round_label': 'rerun-001',
                        'sources': [ref(source)], 'source_records': [{'source': ref(source), 'plan_path': plan,
                            'report_path': report, 'approved_id': 'approved'}],
                        'owners': {task_id: ({'task_manifest': original}, {'baseline': {'base_sha': 'a' * 40}}, ref(source))},
                        'images': [image], 'targets': [_target(task_id, 'openspec', 'detect', None, 'detect-001',
                                                                'a' * 40, original, None)]}
            calls = []
            def fake_scaffold(**kwargs):
                calls.append('scaffold')
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if not target_path.exists():
                    write_json(target_path, public)
                if len(calls) == 1:
                    raise RuntimeError('interrupted')
                return []
            def fake_audit(**kwargs):
                calls.append('gold')
                write_json(target_path.parent / 'isolation-audit.json', {'status': 'PASS'})
            def fake_preflight(**kwargs):
                calls.append('preflight')
                write_json(target_path.parent / 'preflight-summary.json', {'status': 'READY'})
            def fake_verify(task_root, source_task, repository_root):
                self.assertEqual(sha256_file(task_root / 'task.json'), original['sha256'])
                return [ref(task_root / 'task.json'), ref(task_root / 'isolation-audit.json'),
                        ref(task_root / 'preflight-summary.json')]
            with patch('batch.rounds.compile_round', return_value=compiled), \
                 patch('batch.rounds.scaffold_tasks', side_effect=fake_scaffold), \
                 patch('batch.rounds.run_audit', side_effect=fake_audit), \
                 patch('batch.rounds.run_preflight', side_effect=fake_preflight), \
                 patch('batch.rounds._verify_task', side_effect=fake_verify):
                with self.assertRaises(RuntimeError):
                    prepare_round(config, 'rerun-001', root=root)
                self.assertTrue(target_path.is_file())
                self.assertFalse((run / 'prepared-round.json').exists())
                prepared = prepare_round(config, 'rerun-001', root=root)
                self.assertEqual((prepared['target_count'], calls), (1, ['scaffold', 'scaffold', 'gold', 'preflight']))
                self.assertEqual(prepare_round(config, 'rerun-001', root=root), prepared)
                write_json(target_path, {'task_id': task_id, 'tampered': True})
                with self.assertRaises(BatchError):
                    prepare_round(config, 'rerun-001', root=root)


class RoundRuntimeTests(unittest.TestCase):
    def test_formal_compose_catalog_uses_bench_root_for_isolated_task(self) -> None:
        import subprocess
        from unittest.mock import patch
        from batch.stages import _run_compose_agent
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp)
            bench = root / 'sdd-bench/scrapy-sdd'
            task = bench / 'batch/runs/round-test/tasks/task-pr1'
            task.mkdir(parents=True)
            output = task / 'runs/openspec/detect/executions/detect-001/attempt-1'
            output.mkdir(parents=True)
            kwargs = {'task_root': task, 'bench': bench, 'method': 'openspec', 'stage': 'detect',
                      'run_id': 'detect-001', 'mode': None, 'env': {}, 'prompt': 'test',
                      'output': output, 'override': None}
            with patch('batch.stages.subprocess.run') as docker:
                with self.assertRaises(BatchError) as error:
                    _run_compose_agent(**kwargs)
            self.assertEqual(error.exception.code, 'MODEL_CATALOG_MISSING')
            docker.assert_not_called()
            catalog = bench / 'environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-flash/models.json'
            catalog.parent.mkdir(parents=True)
            catalog.write_text('{}')
            with patch('batch.stages.subprocess.run', side_effect=lambda args, **kw: subprocess.CompletedProcess(args, 0, 'services: {}\n', '')) as docker:
                _run_compose_agent(**kwargs)
            self.assertEqual(docker.call_count, 4)
            override = (output / 'codex-catalog.override.yaml').read_text()
            self.assertIn(str(catalog), override)
            self.assertNotIn(str(task.parents[1] / 'environments'), override)


class RoundRetryCliTests(unittest.TestCase):
    def test_retry_failed_selects_only_failed_and_interrupted_targets(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from batch import experiment_cli
        from batch.orchestrator import Ledger, target_key
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp); bench = root / 'sdd-bench/scrapy-sdd'
            schema = bench / 'schemas/batch-ledger-event-v1.schema.json'
            schema.parent.mkdir(parents=True)
            schema.write_bytes((BENCH / 'schemas/batch-ledger-event-v1.schema.json').read_bytes())
            round_id = 'round-' + 'e' * 24
            path = bench / 'batch/runs' / round_id / 'prepared-round.json'
            path.parent.mkdir(parents=True)
            prepared = {'prepared_id': round_id}
            ledger = Ledger(path.parent / 'ledger.jsonl', round_id, schema)
            targets = []
            for method, state in (('openspec', 'FAILED'), ('speckit', 'DETECT_RUNNING'), ('cc-sdd', 'DETECT_SEALED')):
                item = {'task_id': 'task-pr1', 'method': method, 'stage': 'detect', 'run_id': method + '-detect-001', 'mode': None}
                targets.append(item)
                ledger.append('detect', item, state, 1, {'test': True})
            output = io.StringIO()
            with patch.object(experiment_cli, 'BENCH', bench), \
                 patch.object(experiment_cli, '_round_frozen', return_value=(prepared, path)), \
                 patch.object(experiment_cli, 'orchestrate', return_value={'status': 'READY'}) as runner, \
                 patch.object(experiment_cli, 'write_result_view', return_value=({'view_sha256': 'a' * 64}, path.parent / 'result-view.json')), \
                 redirect_stdout(output):
                code = experiment_cli.run(['run', 'config.json', '--round', 'rerun-001', '--stage', 'detect',
                                           '--execute', '--resume', '--retry-failed'])
            self.assertEqual(code, 0)
            self.assertEqual(runner.call_args.kwargs['retries'], {target_key(item) for item in targets[:2]})
            self.assertEqual(json.loads(output.getvalue())['retry_count'], 2)


class RoundViewIntegrityTests(unittest.TestCase):
    def test_stale_ledger_does_not_hide_a_changed_prior_seal(self) -> None:
        from batch.orchestrator import Ledger
        from batch.result_view import load_current_round
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp)
            bench = root / 'sdd-bench/scrapy-sdd'
            schema = bench / 'schemas/batch-ledger-event-v1.schema.json'
            schema.parent.mkdir(parents=True)
            schema.write_bytes((BENCH / 'schemas/batch-ledger-event-v1.schema.json').read_bytes())
            (bench / 'schemas/target-result-view-v2.schema.json').write_bytes(
                (BENCH / 'schemas/target-result-view-v2.schema.json').read_bytes())
            round_id = 'round-' + 'f' * 24
            run = bench / 'batch/runs' / round_id
            run.mkdir(parents=True)
            source = run / 'prepared-round.json'
            write_json(source, {'manifest_type': 'PREPARED_ROUND'})
            ledger = Ledger(run / 'ledger.jsonl', round_id, schema)
            task = {'task_id': 'task-pr1', 'method': 'openspec', 'stage': 'detect',
                    'run_id': 'detect-001', 'mode': None}
            ledger.append('detect', task, 'DETECT_SEALED', 1, {})
            seal = run / 'seal.json'
            write_json(seal, {'status': 'SEALED'})
            key = 'task-pr1:openspec:detect:detect-001:none'
            ref = lambda path: {'path': path.relative_to(root).as_posix(), 'sha256': sha256_file(path)}
            row = {'target_key': key, 'target_id': 'target-' + 'a' * 24,
                   'task_id': 'task-pr1', 'pr_id': 1, 'title': 'test', 'method': 'openspec',
                   'stage': 'detect', 'mode': None, 'run_id': 'detect-001',
                   'state': 'DETECT_SEALED', 'attempt': 1,
                   'ledger_event': {'sequence': 1, 'event_sha256': ledger.read()[-1]['event_sha256']},
                   'execution_path': None, 'seal': ref(seal)}
            view = {'schema_version': 2, 'view_type': 'TARGET_RESULT_VIEW',
                    'batch_id': round_id, 'prepared_id': round_id, 'experiment_id': 'test',
                    'source': {'type': 'round-manifest', **ref(source)},
                    'ledger': {**ref(ledger.path), 'event_count': 1,
                               'chain_tip_sha256': ledger.read()[-1]['event_sha256']},
                    'counts': {'target_count': 1, 'detect_count': 1, 'update_count': 0,
                               'terminal_count': 1, 'states': {'DETECT_SEALED': 1}},
                    'target_order': [key], 'targets': {key: row}}
            view['view_sha256'] = canonical_sha256(view)
            view_path = run / 'result-view.json'
            write_json(view_path, view)
            ledger.append('detect', task, 'SKIPPED_RESUME', 1, {})
            write_json(seal, {'status': 'TAMPERED'})
            with self.assertRaises(BatchError) as error:
                load_current_round(view_path, source, bench, root)
            self.assertEqual(error.exception.code, 'RESULT_VIEW_EVIDENCE_CHANGED')


class ViewerDashboardTests(unittest.TestCase):
    def test_dashboard_reads_each_batch_once_for_its_pr_cards(self) -> None:
        from unittest.mock import patch
        from batch.archive.viewer import module as viewer_module
        viewer = viewer_module(BENCH)
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp)
            batch = viewer.Experiment('round-test', root, 'batch', 0, source_kind='batch', batch_id='round-test')
            cards = [batch, *(viewer.Experiment(f'round-test/task-pr{pr}', root, 'batch', 0,
                         source_kind='batch', batch_id='round-test', task_id_filter=f'task-pr{pr}')
                              for pr in (1, 2))]
            targets = [viewer.BatchTarget(f'task-pr{pr}', pr, 'test', 'openspec', 'detect',
                       'detect-001', None, 'DETECT_SEALED', 1, root) for pr in (1, 2)]
            with patch.object(viewer, 'batch_targets', return_value=targets) as loaded:
                page = viewer.dashboard_html(cards, BENCH)
            loaded.assert_called_once()
            self.assertIn('PR 1', page)
            self.assertIn('PR 2', page)
