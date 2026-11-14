"""End-to-end contracts: two unrelated projects, durability, failures and tampering."""
import json
import os
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path

from test_trace.common import TraceError, digest, read_json, write_json
from test_trace.runner import collect, discover, load_config, _remove_tree, coordinator_lock, Worker
from test_trace.store import aggregate, bundle, verify
from test_trace.query import show, export


PYTEST_PYTHON = os.environ.get('TEST_TRACE_TEST_PYTHON', sys.executable)


class EndToEnd(unittest.TestCase):
    def test_cleanup_timeout_is_a_warning_and_does_not_erase_terminal_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = Worker({'runtime': {'kind': 'docker'}}, root, 1)
            worker.container = 'owned-worker'
            with patch('test_trace.runner.subprocess.run', side_effect=subprocess.TimeoutExpired(['docker', 'rm'], 60)):
                worker.close()
            self.assertIsNone(worker.container)
            warnings = read_json(root/'cleanup-warnings.json')
            self.assertEqual(warnings[0]['container'], 'owned-worker')

    def test_cleanup_readonly_directories_and_exclusive_output_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'readonly'
            directory.mkdir()
            (directory / 'scrapy.cfg').write_text('owned test artifact')
            (directory / 'scrapy.cfg').chmod(0o400)
            directory.chmod(0o500)
            _remove_tree(directory)
            self.assertFalse(directory.exists())
            with coordinator_lock(root / 'run'):
                with self.assertRaises(TraceError):
                    with coordinator_lock(root / 'run'):
                        self.fail('Concurrent writer admitted')

    def config(self, temporary, *, src=False):
        root = Path(temporary)
        repository = root / 'project'
        repository.mkdir()
        package = repository / ('src/library' if src else 'library')
        package.mkdir(parents=True)
        (package / '__init__.py').write_text('def leaf(x):\n    return x + 1\ndef middle(x):\n    return leaf(x)\ndef entry(x):\n    return middle(x)\n')
        (repository / 'tests').mkdir()
        if src:
            (repository / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["src"]\n')
            tests = 'import unittest\nfrom library import entry\nclass Example(unittest.TestCase):\n def test_body(self):\n  self.assertEqual(entry(1), 2)\n'
        else:
            tests = ('import pytest\nfrom library import entry\n'
                     '@pytest.mark.parametrize("x", [1, 2])\ndef test_body(x):\n assert entry(x) == x + 1\n'
                     'def test_failure():\n entry(3)\n assert False\n'
                     '@pytest.mark.skip(reason="explicit")\ndef test_skip():\n pass\n')
        (repository / 'tests/test_example.py').write_text(tests)
        path = root / 'config.json'
        write_json(path, {'repository': str(repository), 'output': str(root / 'run'), 'base_sha': 'a'*40,
                          'production_roots': ['src/library' if src else 'library'], 'timeout_seconds': 20,
                          'runtime': {'kind': 'local', 'python': PYTEST_PYTHON, 'env': {'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}}})
        return load_config(path), root

    def test_flat_project_failure_denominator_query_bundle_and_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, root = self.config(temporary)
            discovery = discover(config)
            self.assertEqual(len(discovery['items']), 4)
            self.assertEqual(collect(config)['completed'], 4)
            index = aggregate(root / 'run')
            self.assertEqual(index['summary']['outcomes'], {'passed': 2, 'failed': 1, 'skipped': 1})
            self.assertEqual(index['summary']['evidence']['valid'], 2)
            body = show(root / 'run', 'tests/test_example.py::test_body', 0)
            self.assertEqual(body['expected_instances'], 2)
            self.assertEqual(len(body['production_covered_functions']), 3)
            self.assertEqual(len(body['edges']), 3)
            failure = show(root / 'run', 'tests/test_example.py::test_failure', 0)
            self.assertIsNone(failure['covered_functions'])
            self.assertTrue(list((root / 'run/diagnostics').glob('*.json')))
            self.assertEqual(collect(config)['completed'], 4)  # unchanged results are not rerun
            failure_path = root / 'run/instances' / (digest('tests/test_example.py::test_failure') + '.json')
            legacy = read_json(failure_path)
            legacy['covered_functions'] = ['diagnostic_trace_must_not_be_published']
            legacy['nodes'] = [{'id': 'diagnostic_trace_must_not_be_published'}]
            write_json(failure_path, legacy)
            sealed = root / 'public'
            self.assertEqual(bundle(root / 'run', sealed)['status'], 'PASS')
            self.assertFalse((sealed / 'diagnostics').exists())
            public_failure = read_json(sealed / 'instances' / failure_path.name)
            self.assertNotIn('nodes', public_failure)
            self.assertNotIn('covered_functions', public_failure)
            html = root / 'body.html'
            export(sealed, 'tests/test_example.py::test_body', html)
            self.assertIn('<svg', html.read_text())
            (sealed / 'symbols.json').write_text('{}')
            with self.assertRaises(TraceError):
                verify(sealed)

    def test_src_layout_and_unittest_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, root = self.config(temporary, src=True)
            config['worker_root'] = str(root / 'disposable-scratch')
            collect(config)
            index = aggregate(root / 'run')
            self.assertEqual(index['summary']['evidence'].get('valid'), 1)
            self.assertEqual(index['summary']['covered_production_functions'], 3)
            self.assertTrue((root / 'disposable-scratch/1/repository').is_dir())
            self.assertFalse((root / 'run/.workers').exists())

    def test_source_change_requires_new_batch_and_bundle_path_is_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, root = self.config(temporary)
            discover(config)
            path = Path(config['repository']) / 'library/__init__.py'
            path.write_text(path.read_text() + '\n# changed\n')
            with self.assertRaises(TraceError):
                collect(config)
            with self.assertRaises(TraceError):
                bundle(root / 'run', root / 'run/methods/public')


if __name__ == '__main__':
    unittest.main()
