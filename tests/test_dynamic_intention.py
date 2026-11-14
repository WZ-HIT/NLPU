"""D preserves C, excludes incomplete traces, and exposes genuine per-instance paths."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from experiment.test_intention import dynamic_bundle, dynamic_reader, dynamic_view, reader, search_view
from experiment.test_intention.stage_b_bundle import checked, write
from test_trace.common import file_hash


class DynamicIntentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.c = self.root/'C'; self.c.mkdir()
        self.trace = self.root/'trace'; self.trace.mkdir()
        self.a, self.b, self.p, self.u, self.n = ['tests/t.py::test_'+x for x in 'abpun']
        self.ids = [self.a, self.b, self.p, self.u, self.n]
        self.f, self.x = 'prod.py::function', 'prod.py::helper'
        with sqlite3.connect(self.c/'.evidence.sqlite3') as db:
            db.executescript('''CREATE TABLE tests(id TEXT PRIMARY KEY,path TEXT,card TEXT,intention TEXT,
                    facts TEXT,context_refs TEXT,uncertainty TEXT,location TEXT);
                CREATE TABLE contexts(id TEXT PRIMARY KEY,metadata TEXT);
                CREATE TABLE edges(source TEXT,target TEXT,relation TEXT,depth INTEGER);
                CREATE TABLE files(path TEXT PRIMARY KEY,metadata TEXT);''')
            for identity in self.ids:
                db.execute('INSERT INTO tests VALUES(?,?,?,?,?,?,?,?)',
                           (identity, 'tests/t.py', json.dumps({'id': identity, 'goal': 'Original TI'}),
                            json.dumps({'summary': 'Original TI', 'scenarios': [{'expected': 'original'}]}),
                            '{}', '[]', '[]', '{}'))
        directory = Path(dynamic_view.__file__).parent
        for source, target in [('stage_b_reader.py', 'read.py'), ('reader.py', 'legacy_read.py'),
                               ('search_view.py', 'search_view.py'), ('sensitivity_view.py', 'sensitivity_view.py'),
                               ('maintenance_view.py', 'maintenance_view.py')]:
            shutil.copyfile(directory/source, self.c/target)
        write(self.c/'README.md', {}); write(self.c/'index.json', {}); write(self.c/'relations.json', {})
        (self.c/'.rgignore').write_text('manifest.json\n')
        manifest = {'base_sha': 'a'*40, 'source_files': {'prod.py': 'hash'},
                    'test_count': len(self.ids), 'material_group': 'C',
                    'representation_format': 'matched-intention-v1',
                    'files': {p.name: file_hash(p) for p in self.c.iterdir()}}
        write(self.c/'manifest.json', manifest)
        # f is actually covered in a's i2, but there is NO root->x->f path in one instance.
        self.docs = [self.document(self.a, [self.f, self.x], [('i1', self.a, self.x), ('i2', self.x, self.f)], 2),
                     self.document(self.b, [self.f], [('i1', self.b, self.f)]),
                     self.document(self.p, ['PARTIAL_CANARY'], [], status='partial'),
                     self.document(self.u, None, [], status='unavailable')]
        self.seal_trace()

    def document(self, identity, covered, edges, instances=1, status='complete'):
        names = ['i'+str(i+1) for i in range(instances)]
        return {'source_test_id': identity, 'coverage_status': status, 'expected_instances': instances,
                'valid_instances': instances if status=='complete' else 1 if status=='partial' else 0,
                'production_covered_functions': covered,
                'instances': [{'execution_id': n, 'evidence_status': 'valid', 'outcome': 'passed'} for n in names],
                'nodes': [{'id': n} for n in {identity, *(covered or []), self.x}],
                'edges': [{'caller': a, 'callee': b, 'kind': 'observed_python_parent',
                           'supporting_instances': [i]} for i, a, b in edges],
                'external_boundaries': []}

    def seal_trace(self):
        entries = []
        for i, doc in enumerate(self.docs):
            relative = f'method-{i}.json'; write(self.trace/relative, doc)
            entries.append({'id': doc['source_test_id'], 'path': relative,
                            **{k: doc[k] for k in ('coverage_status', 'expected_instances', 'valid_instances')}})
        write(self.trace/'index.json', {'base_sha': 'a'*40, 'snapshot_id': 'snapshot', 'tests': entries})
        write(self.trace/'manifest.json', {'base_sha': 'a'*40, 'snapshot_id': 'snapshot',
             'environment_id': 'environment', 'collection_scope': 'test_body_only',
             'source_files': {'prod.py': 'hash'},
             'files': {p.name: file_hash(p) for p in self.trace.iterdir() if p.name!='manifest.json'}})

    def export(self, name='D'):
        target = self.root/name
        dynamic_bundle.export(self.c, self.trace, target, file_hash(self.trace/'manifest.json'))
        return target

    def test_preserves_c_and_no_incomplete_payload_in_any_d_file(self):
        target = self.export()
        self.assertEqual(file_hash(target/'.evidence.sqlite3'), file_hash(self.c/'.evidence.sqlite3'))
        for p in target.rglob('*'):
            if p.is_file(): self.assertNotIn(b'PARTIAL_CANARY', p.read_bytes(), str(p))
        with dynamic_view.connect(target) as db:
            for identity, status in [(self.p,'partial'), (self.u,'unavailable'), (self.n,'not_discovered')]:
                self.assertEqual(dynamic_view.metadata(db, identity)['coverage_status'], status)
                self.assertFalse(dynamic_view.metadata(db, identity)['provided'])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM coverage WHERE test_id=?',(identity,)).fetchone()[0], 0)

    def test_no_spliced_paths_or_fabricated_shallow_shared_neighbor(self):
        target = self.export()
        with dynamic_view.connect(target) as db, reader.connect(target) as evidence:
            self.assertEqual(dynamic_view.shared_rows(db,evidence,self.a), [])
            covered = {r['function']: r for r in dynamic_view.coverage_rows(db,self.a)}
            self.assertIsNone(covered[self.f]['minimum_root_depth'])
            self.assertEqual(covered[self.x]['minimum_root_depth'], 1)
            shallow = dynamic_view.trace_rows(target,db,self.a)
            self.assertFalse(any(r.get('callee') == self.f for r in shallow))
            full = dynamic_view.trace_rows(target,db,self.a,0)
            self.assertTrue(any(r.get('callee') == self.f and r['execution_id']=='i2' for r in full))

    def test_observed_shared_witness_and_frequency_order_are_real(self):
        self.docs[0]['edges'].append({'caller': self.a, 'callee': self.f, 'kind': 'observed_python_parent', 'supporting_instances': ['i2']})
        self.seal_trace(); target=self.export()
        with dynamic_view.connect(target) as db, reader.connect(target) as evidence:
            neighbors=dynamic_view.shared_rows(db,evidence,self.a)
            self.assertEqual([r['id'] for r in neighbors],[self.b])
            self.assertEqual(neighbors[0]['witness']['source_path'],{'execution_id':'i2','nodes':[self.a,self.f]})
            self.assertEqual(neighbors[0]['witness']['covering_complete_test_count'],2)
            self.assertEqual(neighbors[0]['goal_preview'],'Original TI')

    def test_cli_is_readonly_bounded_and_keeps_original_scenarios(self):
        target=self.export(); before=checked(target)
        for argv in [['show',self.a],['coverage',self.a],['trace',self.a],['shared',self.a],['scenarios',self.a]]:
            result=subprocess.run([sys.executable,str(target/'read.py'),*argv],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertLessEqual(len(result.stdout.encode()),6000)
            data=json.loads(result.stdout)
            if argv[0]=='scenarios':self.assertEqual(data['items'],[{'expected':'original'}])
        self.assertEqual(checked(target),before)
        self.assertFalse(list(target.rglob('__pycache__')))

    def test_rejects_base_source_hash_and_invalid_instance_provenance(self):
        manifest=json.loads((self.trace/'manifest.json').read_text());manifest['base_sha']='b'*40
        write(self.trace/'manifest.json',manifest)
        with self.assertRaisesRegex(ValueError,'BASE'):self.export()
        self.seal_trace()
        (self.trace/'method-0.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'TRACE_FILE_CHANGED'):self.export('D2')
        self.docs[0]['edges'][0]['supporting_instances']=['nonexistent'];self.seal_trace()
        with self.assertRaisesRegex(ValueError,'PROVENANCE'):self.export('D3')

    def test_all_neighbors_and_all_witnesses_are_pageable_without_silent_cutoff(self):
        # Several distinct TI tests share f with b; each must remain accessible.
        self.docs[0]['edges'].append({'caller':self.a,'callee':self.f,'kind':'observed_python_parent','supporting_instances':['i1']})
        self.seal_trace();target=self.export()
        for command in [['shared',self.a],['shared',self.a,'--with',self.b],['trace',self.a,'--depth','0']]:
            offset=0; recovered=[]
            while True:
                stream=io.StringIO()
                with redirect_stdout(stream): code=dynamic_reader.main([*command,'--offset',str(offset),'--limit','1'],target)
                self.assertEqual(code,0)
                page=json.loads(stream.getvalue()); recovered.extend(page['items'])
                if page['next_offset'] is None:break
                self.assertGreater(page['next_offset'],offset);offset=page['next_offset']
            self.assertTrue(recovered)


if __name__=='__main__': unittest.main()
