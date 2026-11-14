"""Mechanism checks using tiny generated projects, never benchmark targets."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path

from test_trace.collector import Collector
from test_trace.symbols import SymbolIndex


PROJECT = Path(__file__).resolve().parents[1]


class CollectorMechanisms(unittest.TestCase):
    def test_standalone_coverage_edges_and_failure_restores_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = 'def leaf():\n    return 1\ndef middle():\n    return leaf()\ndef test_body():\n    middle()\n    raise RuntimeError("expected")\n'
            path = root / 'sample.py'
            path.write_text(source)
            namespace = {}
            exec(compile(source, str(path), 'exec'), namespace)
            trace = Collector({'repository_root': str(root), 'production_roots': ['sample.py']})
            old = sys.getprofile()
            trace.arm(namespace['test_body'].__code__, 'sample.py::test_body')
            try:
                with self.assertRaises(RuntimeError):
                    namespace['test_body']()
            finally:
                trace.disarm()
            self.assertIs(sys.getprofile(), old)
            document = trace.document()
            self.assertEqual(document['body_boundary_status'], 'verified')
            self.assertEqual(document['errors'], [])
            self.assertEqual(set(document['covered_functions']), {'sample.py::test_body', 'sample.py::middle', 'sample.py::leaf'})
            self.assertEqual({(e['caller'], e['callee']) for e in document['edges']},
                             {('sample.py::test_body', 'sample.py::middle'), ('sample.py::middle', 'sample.py::leaf')})

    def test_mapping_requires_equal_content_and_uses_ast_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, installed = root / 'repo', root / 'installed'
            repo.mkdir()
            installed.mkdir()
            source = 'class Parent:\n    def test_method(self):\n        pass\nclass Child(Parent):\n    pass\n'
            (repo / 'mod.py').write_text(source)
            (installed / 'mod.py').write_text(source)
            namespace = {}
            exec(compile(source, str(installed / 'mod.py'), 'exec'), namespace)
            index = SymbolIndex(repo, ['mod.py'], [{'runtime_root': str(installed), 'repository_root': '.'}])
            self.assertEqual(index.resolve_callable(namespace['Child']().test_method)['source_test_id'], 'mod.py::Parent.test_method')
            (installed / 'mod.py').write_text(source + '\n# drift\n')
            changed = SymbolIndex(repo, [], [{'runtime_root': str(installed), 'repository_root': '.'}])
            self.assertIsNone(changed.resolve(namespace['Parent'].test_method.__code__))
            self.assertEqual(changed.errors[0]['code'], 'SOURCE_MAPPING_CONTENT_MISMATCH')

    def test_confirmed_test_source_is_not_production_in_embedded_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'checks.py'
            source = 'def verify_case():\n    return 1\n'
            path.write_text(source)
            namespace = {}
            exec(compile(source, str(path), 'exec'), namespace)
            index = SymbolIndex(root, ['.'])
            self.assertEqual(index.resolve(namespace['verify_case'].__code__)['kind'], 'production')
            index.register_test_ids(['checks.py::verify_case'])
            self.assertEqual(index.resolve(namespace['verify_case'].__code__)['kind'], 'test')

    def test_equal_code_objects_in_distinct_files_keep_distinct_symbols(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = 'def same():\n    return 42\n'
            codes = []
            for name in ('one.py', 'two.py'):
                path = root / name
                path.write_text(source)
                namespace = {}
                exec(compile(source, str(path), 'exec'), namespace)
                codes.append(namespace['same'].__code__)
            self.assertEqual(codes[0], codes[1])
            self.assertIsNot(codes[0], codes[1])
            index = SymbolIndex(root)
            self.assertEqual(index.resolve(codes[0])['id'], 'one.py::same')
            self.assertEqual(index.resolve(codes[1])['id'], 'two.py::same')

    def test_snapshot_rejects_modified_and_generated_runtime_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = 'def base():\n    return 1\n'
            path = root / 'app.py'
            path.write_text(original)
            index = SymbolIndex(root, ['.'], source_files={'app.py': hashlib.sha256(original.encode()).hexdigest()})
            namespace = {}
            exec(compile(original, str(path), 'exec'), namespace)
            self.assertIsNotNone(index.resolve(namespace['base'].__code__))
            changed = 'def base():\n    return 2\n'
            path.write_text(changed)
            exec(compile(changed, str(path), 'exec'), namespace)
            self.assertIsNone(index.resolve(namespace['base'].__code__))
            generated = root / 'generated.py'
            generated.write_text(original)
            exec(compile(original, str(generated), 'exec'), namespace)
            self.assertIsNone(index.resolve(namespace['base'].__code__))
            self.assertEqual(index.errors, [{'code': 'SOURCE_CONTENT_CHANGED', 'path': 'app.py'}])
            self.assertIn('generated_or_non_snapshot_sources_excluded', index.limitations)


@unittest.skipUnless(importlib.util.find_spec('pytest'), 'pytest is required only for adapter mechanism checks')
class PytestAdapterMechanisms(unittest.TestCase):
    def run_project(self, files, *, nodeid=None, discover=False, extra_env=None):
        with tempfile.TemporaryDirectory() as temporary:
            outer = Path(temporary)
            repo = outer / 'repository'
            repo.mkdir()
            for relative, content in files.items():
                target = repo / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(textwrap.dedent(content).lstrip(), encoding='utf-8')
            output = outer / 'result.json'
            config = {'mode': 'discover' if discover else 'collect', 'repository_root': str(repo),
                      'production_roots': ['app.py'], 'source_mappings': [], 'output_file': str(output),
                      'snapshot_id': 'mechanism-fixture', 'base_sha': None, 'raw_events': True,
                      'execution_id': nodeid}
            config['source_files'] = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in repo.rglob('*') if p.is_file()}
            settings = outer / 'config.json'
            settings.write_text(json.dumps(config))
            env = dict(os.environ, TEST_TRACE_CONFIG=str(settings), PYTHONPATH=str(PROJECT),
                       PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1')
            env.update(extra_env or {})
            command = [sys.executable, '-m', 'pytest', '-q', '-p', 'test_trace.pytest_plugin', '-p', 'no:cacheprovider']
            command.extend(['--collect-only'] if discover else [nodeid])
            run = subprocess.run(command, cwd=repo, env=env, text=True, capture_output=True, timeout=40)
            self.assertTrue(output.is_file(), run.stdout + run.stderr)
            document = json.loads(output.read_text())
            document['_pytest_output'] = run.stdout + run.stderr
            return document

    def assert_valid(self, document):
        self.assertEqual(document['evidence_status'], 'valid', document)
        self.assertEqual(document['errors'], [], document)

    def test_sync_multilevel_excludes_setup_teardown_and_dynamic_fixture(self):
        document = self.run_project({
            'app.py': '''
                def setup_only(): pass
                def teardown_only(): pass
                def fixture_only(): pass
                def leaf(): return 3
                def middle(): return leaf()
            ''',
            'test_sample.py': '''
                import pytest
                import app
                def setup_function(): app.setup_only()
                def teardown_function(): app.teardown_only()
                @pytest.fixture
                def late():
                    app.fixture_only()
                    return 3
                def helper(): return app.middle()
                def test_body(request):
                    assert request.getfixturevalue('late') == 3
                    assert helper() == 3
            '''}, nodeid='test_sample.py::test_body')
        self.assert_valid(document)
        self.assertEqual(document['production_covered_functions'], ['app.py::leaf', 'app.py::middle'])
        self.assertIn('test_sample.py::helper', document['covered_functions'])
        self.assertNotIn('test_sample.py::late', document['covered_functions'])
        self.assertIn(('app.py::middle', 'app.py::leaf'), {(e['caller'], e['callee']) for e in document['edges']})

    def test_unittest_cleanup_excluded_even_when_called_inside_body(self):
        document = self.run_project({
            'app.py': '''
                def setup_only(): pass
                def teardown_only(): pass
                def cleanup_only(): pass
                def body(): return 4
            ''',
            'test_sample.py': '''
                import unittest
                import app
                class Example(unittest.TestCase):
                    def setUp(self):
                        app.setup_only()
                        self.addCleanup(app.cleanup_only)
                    def tearDown(self): app.teardown_only()
                    def test_body(self):
                        self.assertEqual(app.body(), 4)
                        self.doCleanups()
            '''}, nodeid='test_sample.py::Example::test_body')
        self.assert_valid(document)
        self.assertEqual(document['production_covered_functions'], ['app.py::body'])

    def test_async_resumes_and_excludes_async_setup_cleanup_background(self):
        document = self.run_project({
            'app.py': '''
                def before(): return 1
                def after(): return 2
                def setup_background(): return 3
                def setup_only(): pass
                def teardown_only(): pass
                def cleanup_only(): pass
                def spawned(): return 9
            ''',
            'test_sample.py': '''
                import unittest
                import asyncio
                import app
                class Example(unittest.IsolatedAsyncioTestCase):
                    async def asyncSetUp(self):
                        app.setup_only()
                        self.addAsyncCleanup(self.cleanup)
                        async def background():
                            await asyncio.sleep(0)
                            app.setup_background()
                        self.background = asyncio.create_task(background())
                    async def asyncTearDown(self): app.teardown_only()
                    async def cleanup(self): app.cleanup_only()
                    async def test_body(self):
                        self.assertEqual(app.before(), 1)
                        await asyncio.sleep(0)
                        async def child():
                            await asyncio.sleep(0)
                            return app.spawned()
                        self.assertEqual(await asyncio.create_task(child()), 9)
                        await self.background
                        await asyncio.sleep(0)
                        self.assertEqual(app.after(), 2)
            '''}, nodeid='test_sample.py::Example::test_body')
        self.assert_valid(document)
        self.assertEqual(document['production_covered_functions'], ['app.py::after', 'app.py::before', 'app.py::spawned'])
        self.assertGreaterEqual(len(document['external_boundaries']), 1)

    def test_external_callback_keeps_boundary_without_fabricated_edge(self):
        document = self.run_project({
            'app.py': 'def key(value):\n    return value\n',
            'test_sample.py': '''
                import app
                def test_body():
                    assert sorted([2, 1], key=app.key) == [1, 2]
            '''}, nodeid='test_sample.py::test_body')
        self.assert_valid(document)
        self.assertIn('python_functions_only', document['limitations'])
        self.assertIn('app.py::key', document['production_covered_functions'])
        self.assertNotIn(('test_sample.py::test_body', 'app.py::key'),
                         {(e['caller'], e['callee']) for e in document['edges']})
        self.assertTrue(any(b['direction'] == 'external_c_entry' and b['external_qualified_name'] == 'sorted'
                            for b in document['external_boundaries']), document)

    def test_external_python_scope_keeps_disconnected_entry(self):
        document = self.run_project({
            'app.py': 'def before(): pass\ndef after(): pass\n',
            'test_sample.py': '''
                import contextlib
                import app
                @contextlib.contextmanager
                def scope():
                    app.before()
                    yield
                    app.after()
                def test_body():
                    with scope(): pass
            '''}, nodeid='test_sample.py::test_body')
        self.assert_valid(document)
        self.assertEqual(document['production_covered_functions'], ['app.py::after', 'app.py::before'])
        edges = {(edge['caller'], edge['callee']) for edge in document['edges']}
        self.assertNotIn(('test_sample.py::test_body', 'test_sample.py::scope'), edges)
        self.assertIn(('test_sample.py::scope', 'app.py::before'), edges)
        self.assertTrue(any(boundary['project_function'] == 'test_sample.py::scope'
                            and boundary['direction'] in {'external_entry', 'external_c_entry'}
                            for boundary in document['external_boundaries']))

    def test_decorator_pre_and_post_execution_are_outside_source_body(self):
        document = self.run_project({
            'app.py': 'def before(): pass\ndef after(): pass\ndef body(): pass\n',
            'test_sample.py': '''
                import functools
                import app
                def decorator(function):
                    @functools.wraps(function)
                    def wrapper():
                        app.before()
                        function()
                        app.after()
                    return wrapper
                @decorator
                def test_body(): app.body()
            '''}, nodeid='test_sample.py::test_body')
        self.assert_valid(document)
        self.assertEqual(document['production_covered_functions'], ['app.py::body'])

    def test_discovery_retains_parameter_instances_and_source_owner(self):
        document = self.run_project({'test_sample.py': '''
            import pytest
            class Base:
                @pytest.mark.parametrize('value', [1, 2])
                def test_body(self, value): assert value
            class TestChild(Base): pass
        '''}, discover=True)
        self.assertEqual(document['exit_code'], 0, document)
        self.assertEqual(len(document['items']), 2)
        self.assertEqual(len({item['execution_id'] for item in document['items']}), 2)
        self.assertEqual({item['source_test_id'] for item in document['items']}, {'test_sample.py::Base.test_body'})

    def test_failure_keeps_diagnostic_trace(self):
        document = self.run_project({'app.py': 'def used(): return 1\n', 'test_sample.py': '''
            import app
            def test_body(): assert app.used() == 0
        '''}, nodeid='test_sample.py::test_body')
        self.assertEqual(document['outcome'], 'failed', document)
        self.assertEqual(document['evidence_status'], 'diagnostic')
        self.assertIn('app.py::used', document['covered_functions'])

    def test_setup_failure_preserves_unknown_body_instead_of_empty_valid_graph(self):
        document = self.run_project({'test_sample.py': '''
            def setup_function(): raise RuntimeError('fixture failed')
            def test_body(): pass
        '''}, nodeid='test_sample.py::test_body')
        self.assertEqual(document['body_boundary_status'], 'unknown', document)
        self.assertEqual(document['evidence_status'], 'unsupported')
        self.assertEqual(document['covered_functions'], [])


if __name__ == '__main__':
    unittest.main()
