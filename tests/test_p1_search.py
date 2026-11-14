import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from experiment.test_intention import reader, search_view as search
from experiment.test_intention.p1_bundle import export


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for src, dest in (('reader.py', 'read.py'), ('search_view.py', 'search_view.py')):
            shutil.copyfile(Path(reader.__file__).with_name(src), self.root/dest)
        with sqlite3.connect(self.root/'.evidence.sqlite3') as db:
            db.execute('CREATE TABLE tests(id TEXT PRIMARY KEY,path TEXT,card TEXT,intention TEXT,facts TEXT,context_refs TEXT,uncertainty TEXT,location TEXT)')
            db.execute('CREATE TABLE edges(source TEXT,target TEXT,relation TEXT,depth INTEGER)')
            db.execute('CREATE TABLE contexts(id TEXT,metadata TEXT)')
            db.execute('CREATE TABLE files(path TEXT,metadata TEXT)')
            for i in range(45):
                identity = f'tests/test_example.py::Example.test_{i:02}'
                intention = {'summary': 'Checks the common behavior.', 'scenarios': [
                    {'conditions': ['Straße🙂 under condition'], 'actions': ['invoke operation'],
                     'expected': ['result must stay paired'], 'evidence': ['not searchable metadata']}]} if i else None
                facts = {'calls': [{'expression': 'rare_api(config="KEY")' if not i else 'common_api()',
                                    'line': 12, 'status': 'unresolved'}], 'mock': []}
                card = {'id': identity, 'status': 'GENERATED' if i else 'STATIC_FALLBACK',
                        'goal': 'long card '+('🙂'*1800 if i == 1 else 'x'*800)}
                db.execute('INSERT INTO tests VALUES(?,?,?,?,?,?,?,?)', (identity, 'tests/test_example.py',
                           search.encoded(card), search.encoded(intention), search.encoded(facts), '[]', '[]',
                           '{"path":"tests/test_example.py","start_line":10,"end_line":20}'))
            db.execute('INSERT INTO edges VALUES(?,?,?,1)', ('tests/test_example.py::Example.test_00', 'helper.py::Fixture', 'uses_fixture'))
        self.coverage = search.build_index(self.root/'.evidence.sqlite3', self.root/'.search.sqlite3')
        self.identity = 'tests/test_example.py::Example.test_00'

    def call(self, *args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = reader.main(list(args), root=self.root)
        output = stream.getvalue()
        return code, json.loads(output), len(output.encode())

    def test_fallback_saved_facts_search_and_exact_lookup(self):
        before = search.sha(self.root/'.evidence.sqlite3')
        code, result, size = self.call('search', '--query', 'rare_api')
        self.assertEqual(code, 0)
        hit = result['items'][0]
        self.assertEqual(hit['id'], self.identity)
        self.assertEqual(hit['status'], 'STATIC_FALLBACK')
        self.assertEqual(hit['goal'], '')
        self.assertEqual(hit['hit']['field'], 'facts.calls')
        code, evidence, _ = self.call('match', self.identity, '--ref', hit['hit']['ref'])
        item = evidence['items'][0]
        self.assertEqual(item['context']['line'], 12)
        self.assertEqual(hit['hit']['text'], item['value'][hit['hit']['start']:hit['hit']['end']])
        self.assertEqual(before, search.sha(self.root/'.evidence.sqlite3'))
        self.assertEqual(self.coverage['status']['STATIC_FALLBACK'], 1)
        self.assertEqual(self.coverage['fields']['semantic.summary']['empty_or_missing'], 1)

    def test_unicode_offsets_and_scenario_pair_are_faithful(self):
        code, result, _ = self.call('search', '--query', 'STRASSE', '--limit', '1')
        self.assertEqual(code, 0)
        row = result['items'][0]
        code, result, _ = self.call('match', row['id'], '--ref', row['hit']['ref'])
        item = result['items'][0]
        self.assertEqual(item['context']['expected'], ['result must stay paired'])
        self.assertEqual(item['context']['actions'], ['invoke operation'])
        self.assertEqual(item['value'][row['hit']['match_start']:row['hit']['match_end']], 'Straße')
        self.assertEqual(item['value'][row['hit']['start']:row['hit']['end']], row['hit']['text'])

    def test_boolean_fields_and_metadata_exclusion(self):
        for term in ('unresolved', 'not searchable metadata'):
            self.assertEqual(self.call('search', '--query', term)[1]['matched_test_count'], 0)
        self.assertEqual(self.call('search', '--query', 'rare_api', '--query', 'common_api', '--mode', 'and')[1]['matched_test_count'], 0)
        self.assertEqual(self.call('search', '--query', 'rare_api', '--query', 'common_api')[1]['matched_test_count'], 45)
        self.assertEqual(self.call('search', '--query', 'rare_api', '--search-field', 'semantic.summary')[1]['matched_test_count'], 0)
        self.assertEqual(self.call('search', '--search-field', 'does-not-exist')[0], 1)
        self.assertEqual(self.call('match', self.identity, '--ref', '/facts/calls/0/status')[0], 1)

    def test_no_duplicate_or_missing_results_across_cursors(self):
        for cap in (4096, 6000, 12000):
            rows, next_cursor = [], None
            while True:
                args = ['search', '--sort', 'id', '--limit', '25', '--max-bytes', str(cap)]
                if next_cursor:
                    args += ['--cursor', next_cursor]
                code, page, size = self.call(*args)
                self.assertEqual(code, 0)
                self.assertLessEqual(size, cap)
                self.assertTrue(page['items'])
                rows.extend(r['id'] for r in page['items'])
                next_cursor = page['next_cursor']
                if not next_cursor:
                    break
            self.assertEqual(len(rows), 45)
            self.assertEqual(len(set(rows)), 45)
            self.assertEqual(rows, sorted(rows))

    def test_cursor_rejects_query_sort_reader_evidence_and_index_changes(self):
        cursor = self.call('search', '--limit', '1')[1]['next_cursor']
        self.assertEqual(self.call('search', '--limit', '1', '--cursor', cursor, '--query', 'rare')[0], 1)
        self.assertEqual(self.call('search', '--limit', '1', '--cursor', cursor, '--sort', 'id')[0], 1)
        self.assertEqual(self.call('search', '--cursor', 'not-a-cursor')[0], 1)
        for filename in ('read.py', 'search_view.py', '.evidence.sqlite3', '.search.sqlite3'):
            path = self.root/filename
            saved = path.read_bytes()
            path.write_bytes(saved+b'\n')
            code, result, _ = self.call('search', '--limit', '1', '--cursor', cursor)
            self.assertEqual(code, 1)
            self.assertIn('STALE_OR_INVALID_CURSOR', result['message'])
            path.write_bytes(saved)

    def test_sort_eligibility_exact_identity_and_stability(self):
        docs, stats = search.load_index(self.root)
        sets = []
        for sort in search.SORTS:
            ranked = search.rank(docs, stats, ['common', 'rare_api'], sort=sort)
            sets.append({d['id'] for d, _, _ in ranked})
            self.assertEqual(ranked, search.rank(docs, stats, ['common', 'rare_api'], sort=sort))
        self.assertEqual(sets[0], sets[1]); self.assertEqual(sets[1], sets[2])
        row = self.call('search', '--query', self.identity)[1]['items'][0]
        self.assertEqual(row['id'], self.identity)
        self.assertEqual(row['hit']['field'], 'identity')

    def test_raw_scores_and_order_are_equal_across_hash_seeds(self):
        script = '''import json,pathlib,search_view as s
docs,stats=s.load_index(pathlib.Path('.'))
queries=['common','API','Checks','behavior','rare','config','KEY','under','condition','result','stay','paired']
print(json.dumps({sort:[(d['id'],score) for d,hits,score in s.rank(docs,stats,queries,sort=sort)] for sort in s.SORTS}))
'''
        outputs = []
        for seed in ('0', '1', '77'):
            result = subprocess.run(['python3', '-B', '-c', script], cwd=self.root,
                                    env=dict(os.environ, PYTHONHASHSEED=seed), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])

    def test_fragment_paging_reassembles_long_identity_under_byte_cap(self):
        identity = 'tests.py::'+('名🙂'*1500)
        rows = [{'id': identity, 'status': 'STATIC_FALLBACK'}]
        chunks, offset = [], 0
        while True:
            page = search.search_page(rows, 'binding', offset, 25, 4096, reader.page)
            self.assertLessEqual(len(search.encoded(page).encode())+1, 4096)
            self.assertEqual(page['returned_complete_test_count'], 0)
            chunks.extend(page['items'])
            if not page['next_cursor']:
                break
            offset = search.cursor_offset(page['next_cursor'], 'binding')
        self.assertEqual([c['fragment'] for c in chunks], list(range(chunks[0]['fragments'])))
        self.assertEqual(json.loads(''.join(c['text'] for c in chunks))['id'], identity)

    def test_copied_reader_is_standalone(self):
        result = subprocess.run(['python3', '-B', str(self.root/'read.py'), 'search', '--query', 'rare_api'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['items'][0]['id'], self.identity)
        self.assertFalse((self.root/'__pycache__').exists())


class BundleTests(unittest.TestCase):
    def fixture(self):
        from tests.test_compact_intention import CompactTests
        from experiment.test_intention.compact import export_base
        fixture = CompactTests('test_identity_scenarios_evidence_and_no_source_duplication')
        # Use the existing canonical-data fixture without inheriting or duplicating its tests.
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        export_base(fixture.source, fixture.dest)
        return fixture

    def test_export_preserves_all_evidence_and_input_hashes(self):
        fixture = self.fixture()
        parent = search.sha(fixture.dest/'manifest.json')
        evidence = search.sha(fixture.dest/'.evidence.sqlite3')
        destination = fixture.root/'p1'
        result = export(fixture.dest, destination)
        self.assertEqual(result['coverage']['tests'], 2)
        self.assertEqual(search.sha(destination/'.evidence.sqlite3'), evidence)
        self.assertEqual(search.sha(fixture.dest/'manifest.json'), parent)
        from batch.test_intention import verify_bundle
        verify_bundle(destination/'manifest.json', 'a'*40)
        with self.assertRaises(ValueError):
            export(fixture.dest, destination)
        (destination/'search_view.py').write_text('changed')
        from batch.core import BatchError
        with self.assertRaises(BatchError):
            verify_bundle(destination/'manifest.json', 'a'*40)

    def test_modified_parent_rejected_before_export(self):
        fixture = self.fixture()
        (fixture.dest/'README.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Parent hash changed'):
            export(fixture.dest, fixture.root/'p1')
        self.assertFalse((fixture.root/'p1').exists())


if __name__ == '__main__':
    unittest.main()
