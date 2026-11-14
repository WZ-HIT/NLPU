from pathlib import Path
import tempfile
import unittest

from experiment.test_intention.static import SourceIndex, build, batches, digest
from experiment.test_intention.generation import Generator, validate


class IntentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def put(self, path, source):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)

    def example(self):
        self.put('app/client.py', 'class Client:\n    def fetch(self, path):\n        return path\n')
        self.put('tests/helpers.py', 'def make_value():\n    return 3\n')
        self.put('tests/conftest.py', 'import pytest\n@pytest.fixture\ndef value():\n    return 3\n')
        self.put('tests/test_one.py', '''import pytest
from app.client import Client as C
from tests.helpers import make_value as make

class TestClient:
    def setUp(self):
        self.setting = make()
    def test_fetch(self):
        client = C()
        result = client.fetch('/x')
        assert result == '/x'
    async def test_async(self):
        assert make() == 3

def test_fixture(value):
    assert value == 3

@pytest.mark.parametrize('number', [1, 2])
def test_parameter(number):
    assert number > 0
''')

    def test_aliases_context_assertions_and_source_identity(self):
        self.example()
        document = build(self.root, 'a' * 40)
        self.assertEqual(document['test_count'], 4)
        test = next(t for t in document['tests'] if t['id'].endswith('TestClient.test_fetch'))
        fetch = next(c for c in test['static']['calls'] if c['name'] == 'client.fetch')
        self.assertEqual(fetch['targets'], ['app/client.py::Client.fetch'])
        self.assertTrue(any(c['id'].endswith('.setUp') for c in test['contexts']))
        self.assertEqual(len(test['static']['assertions']), 1)
        fixture = next(t for t in document['tests'] if t['qualified_name'] == 'test_fixture')
        self.assertTrue(any(c['id'] == 'tests/conftest.py::value' for c in fixture['contexts']))
        parametrized = next(t for t in document['tests'] if t['qualified_name'] == 'test_parameter')
        self.assertFalse(any(l['relation'] == 'uses_fixture' for l in parametrized['static']['dependency_links']))

    def test_nested_functions_are_not_outer_calls_or_tests(self):
        self.put('tests/test_scope.py', 'def test_outer():\n    def test_nested():\n        hidden()\n    class Hidden:\n        def test_hidden(self): pass\n    assert True\n')
        document = build(self.root, 'a' * 40)
        self.assertEqual(document['test_count'], 1)
        self.assertFalse(document['tests'][0]['static']['calls'])

    def test_duplicate_test_identity_is_rejected(self):
        self.put('tests/test_duplicate.py', 'def test_x(): pass\ndef test_x(): pass\n')
        with self.assertRaisesRegex(ValueError, 'TESTCASE_ID_AMBIGUOUS'):
            build(self.root, 'a' * 40)

    def test_helper_module_settings_invalidate_cache(self):
        self.put('app/helper.py', 'LIMIT=3\ndef helper():\n    return LIMIT\n')
        self.put('tests/test_limit.py', 'from app.helper import helper\ndef test_limit():\n    assert helper() == 3\n')
        first = list(batches(build(self.root, 'a' * 40)))
        self.put('app/helper.py', 'LIMIT=4\ndef helper():\n    return LIMIT\n')
        second = list(batches(build(self.root, 'b' * 40)))
        self.assertNotEqual(first, second)
        small_first = list(batches(build(self.root, 'a' * 40, max_context_chars=1)))
        self.put('app/helper.py', 'LIMIT=5\ndef helper():\n    return LIMIT\n')
        small_second = list(batches(build(self.root, 'b' * 40, max_context_chars=1)))
        self.assertNotEqual(small_first, small_second)

    def test_branch_receiver_preserves_multiple_candidates(self):
        self.put('app.py', 'class A:\n    def fetch(self): pass\nclass B:\n    def fetch(self): pass\n')
        self.put('tests/test_branch.py', 'from app import A, B\ndef test_x(flag):\n    if flag: c=A()\n    else: c=B()\n    c.fetch()\n')
        result = build(self.root, 'a' * 40)
        call = next(c for c in result['tests'][0]['static']['calls'] if c['name'] == 'c.fetch')
        self.assertEqual(call['status'], 'ambiguous')
        self.assertEqual(len(call['targets']), 2)

    def test_production_class_setting_invalidates_cache(self):
        self.put('app.py', 'class Client:\n    RETRIES=3\n    def fetch(self): return self.RETRIES\n')
        self.put('tests/test_class.py', 'from app import Client\ndef test_x():\n    c=Client()\n    assert c.fetch() == 3\n')
        first = list(batches(build(self.root, 'a' * 40)))
        self.put('app.py', 'class Client:\n    RETRIES=4\n    def fetch(self): return self.RETRIES\n')
        self.assertNotEqual(first, list(batches(build(self.root, 'b' * 40))))

    def test_interrupted_request_is_not_sent_again(self):
        import json
        packet = {'tests': [{'id': 'tests/a.py::test_a', 'contexts': []}], 'contexts': []}
        generator = Generator(self.root / 'cache', secret=self.root / 'unused')
        (generator.request_log / 'prior.json').write_text(json.dumps({
            'input_sha256': generator.key(packet), 'reservation_cny': 0.1,
            'status': 'REQUEST_STARTED', 'usage': None}))
        resumed = Generator(self.root / 'cache', secret=self.root / 'unused')
        result = resumed.generate(packet)
        self.assertEqual(result['status'], 'STATIC_FALLBACK')
        self.assertEqual(resumed.calls, 1)

    def test_incomplete_response_retains_billed_usage(self):
        class Fake(Generator):
            def _request(self, *args):
                return '', {'input_tokens': 100, 'output_tokens': 16384}, 'deepseek-flash', 'fake', 'incomplete'
        packet = {'tests': [{'id': 'tests/a.py::test_a', 'contexts': []}], 'contexts': []}
        record = Fake(self.root / 'cache', secret=self.root / 'unused').generate(packet)
        self.assertEqual(record['status'], 'STATIC_FALLBACK')
        self.assertEqual(record['usage'][0]['output_tokens'], 16384)
        self.assertEqual(record['attempts'][0]['status'], 'incomplete')

    def test_same_leaf_names_are_not_merged(self):
        self.put('one.py', 'def get():\n    pass\n')
        self.put('two.py', 'def get():\n    pass\n')
        self.put('tests/test_names.py', 'from one import get\ndef test_get():\n    assert get() is None\n')
        document = build(self.root, 'a' * 40)
        self.assertEqual(document['tests'][0]['static']['calls'][0]['targets'], ['one.py::get'])

    def test_cache_changes_for_setup_or_other_batch_member(self):
        self.example()
        first = list(batches(build(self.root, 'a' * 40)))
        same_source_new_base = list(batches(build(self.root, 'b' * 40)))
        self.assertEqual(first, same_source_new_base)
        source = (self.root / 'tests/helpers.py').read_text()
        self.put('tests/helpers.py', source.replace('return 3', 'return 4'))
        changed = list(batches(build(self.root, 'c' * 40)))
        self.assertNotEqual(digest(first), digest(changed))
        initial = first[0]
        copied = dict(initial)
        copied['tests'] = [dict(t) for t in initial['tests']]
        copied['tests'][0]['source'] += '\n# changed peer\n'
        generator = Generator(self.root / 'cache', secret=self.root / 'unused')
        self.assertNotEqual(generator.key(initial), generator.key(copied))

    def test_validation_rejects_foreign_ids_or_evidence(self):
        packet = {'tests': [{'id': 'tests/a.py::test_a', 'contexts': []}], 'contexts': []}
        record = {'id': 'tests/a.py::test_a', 'summary': 'Checks a value.', 'operations': [],
                  'inputs': [], 'environment_mock': [], 'uncertainties': [],
                  'scenarios': [{'conditions': [], 'actions': [], 'expected': [],
                                 'evidence': ['tests/a.py::test_a']}]}
        validate({'tests': [record]}, packet)
        record['scenarios'][0]['evidence'].append('tests/b.py::other')
        with self.assertRaises(ValueError):
            validate({'tests': [record]}, packet)

    def test_one_repair_then_static_fallback_and_cache_reuse(self):
        packet = {'tests': [{'id': 'tests/a.py::test_a', 'contexts': []}], 'contexts': []}

        class Fake(Generator):
            calls_made = 0

            def _request(self, *args):
                self.calls_made += 1
                return '{}', {'total_tokens': 2}, 'deepseek-flash', 'synthetic'

        generator = Fake(self.root / 'cache', secret=self.root / 'unused')
        record = generator.generate(packet)
        self.assertEqual(generator.calls_made, 2)
        self.assertEqual(record['status'], 'STATIC_FALLBACK')
        generator.generate(packet)
        self.assertEqual(generator.calls_made, 2)


if __name__ == '__main__':
    unittest.main()
