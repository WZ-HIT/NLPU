import contextlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from experiment.test_intention import reader, search_view as search
from experiment.test_intention.maintenance_static import Extractor, MAX_CALLS
from experiment.test_intention import maintenance_view as view
from experiment.test_intention.p2_bundle import export


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root/'repository'
        (self.repo/'tests').mkdir(parents=True)
        (self.repo/'lib.py').write_text('raise RuntimeError("MUST NEVER IMPORT")\nclass Spider: pass\ndef rare_factory(): pass\n')
        self.source = '''from lib import Spider as S, rare_factory as factory, unused
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from optional import ConditionAlias

class Base:
    def setUp(self):
        self.spider = factory()

class Example(Base):
    def test_plain(self):
        assert self.spider

    def test_typed(self, value: "S") -> S:
        π: S = None
        assert π is None

    def test_local(self):
        from alternative import choice as factory
        factory()
        def hidden():
            x: HiddenAnnotation = hidden_call()

    def test_shadow(self, factory):
        factory()

    def test_guard(self, value: "ConditionAlias"):
        assert value
'''
        (self.repo/'tests/test_sample.py').write_text(self.source)
        self.extractor = Extractor(self.repo)
        self.identity = 'tests/test_sample.py::Example.test_typed'
        self.parent = self.root/'p1'
        self.parent.mkdir()
        self.destination = self.root/'workspace/test-intentions'
        with sqlite3.connect(self.parent/'.evidence.sqlite3') as db:
            db.execute('CREATE TABLE tests(id TEXT PRIMARY KEY,path TEXT,card TEXT,intention TEXT,facts TEXT,context_refs TEXT,uncertainty TEXT,location TEXT)')
            db.execute('CREATE TABLE edges(source TEXT,target TEXT,relation TEXT,depth INTEGER)')
            db.execute('CREATE TABLE contexts(id TEXT,metadata TEXT)')
            db.execute('CREATE TABLE files(path TEXT,metadata TEXT)')
            for identity in self.extractor.index.tests():
                symbol = self.extractor.index.symbols[identity]
                card = {'id': identity, 'status': 'STATIC_FALLBACK', 'goal': None}
                refs = ['tests/test_sample.py::Base.setUp']
                location = {k: symbol[k] for k in ('path','start_line','end_line')}
                db.execute('INSERT INTO tests VALUES(?,?,?,?,?,?,?,?)',
                    (identity,symbol['path'],search.encoded(card),'null','{}',search.encoded(refs),'["original unknown"]',search.encoded(location)))
                db.execute('INSERT INTO edges VALUES(?,?,?,1)', (identity, refs[0], 'initialization-definition'))
        search.build_index(self.parent/'.evidence.sqlite3', self.parent/'.search.sqlite3')
        for name in ('README.md','index.json','relations.json'):
            (self.parent/name).write_text('{}')
        for src, dest in (('reader.py','read.py'),('search_view.py','search_view.py')):
            shutil.copyfile(Path(reader.__file__).with_name(src),self.parent/dest)
        manifest = {'base_sha': 'a'*40, 'representation_format': 'compact-intention-v3',
                    'source_files': {p:f['sha256'] for p,f in self.extractor.index.files.items()},
                    'files': {p.name:search.sha(p) for p in self.parent.iterdir()}}
        (self.parent/'manifest.json').write_text(json.dumps(manifest))

    def build(self):
        return export(self.parent,self.repo,self.destination)

    def call(self,*args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code=reader.main(list(args),root=self.destination,repository=self.repo)
        return code,json.loads(output.getvalue()),len(output.getvalue().encode())

    def test_annotations_inheritance_and_context_are_distinct_from_direct_facts(self):
        before = search.sha(self.parent/'.evidence.sqlite3')
        result=self.build()
        self.assertEqual(result['coverage']['tests'],5)
        self.assertEqual(search.sha(self.destination/'.evidence.sqlite3'),before)
        code,page,size=self.call('search','--query','rare_factory','--search-field','maintenance.imports')
        self.assertEqual(code,0)
        self.assertTrue(page['items'])
        code,page,size=self.call('search','--query','factory()','--search-field','maintenance.context_calls')
        self.assertEqual(code,0)
        self.assertEqual(page['matched_test_count'],5)
        facts,coverage=view.load(self.destination,self.identity)
        self.assertEqual([f['text'] for f in facts['annotations']],['"S"','S','S'])
        self.assertEqual(facts['inheritance'][0]['text'],'Base')
        self.assertEqual(facts['inheritance'][0]['targets'],['tests/test_sample.py::Base'])
        self.assertFalse(any('HiddenAnnotation' in f['text'] for rows in facts.values() for f in rows))

    def test_imports_respect_parameter_shadow_local_binding_and_actual_usage(self):
        self.build()
        facts,_=view.load(self.destination,'tests/test_sample.py::Example.test_shadow')
        own=[f for f in facts['imports'] if f['scope'].endswith('test_shadow')]
        self.assertEqual(own,[])
        facts,_=view.load(self.destination,'tests/test_sample.py::Example.test_local')
        own=[f for f in facts['imports'] if f['scope'].endswith('test_local')]
        self.assertEqual(len(own),1)
        self.assertEqual(own[0]['targets'],['alternative.choice'])
        self.assertFalse(any(f['binding']=='unused' for f in facts['imports']))

    def test_conditional_import_keeps_branch_uncertainty(self):
        self.build()
        facts,_=view.load(self.destination,'tests/test_sample.py::Example.test_guard')
        imports=[f for f in facts['imports'] if f['binding']=='ConditionAlias']
        self.assertTrue(imports)
        self.assertIn('conditional import',imports[0]['uncertainty'])
        self.assertTrue(any(f['text']=='TYPE_CHECKING' for f in facts['guards']))

    def test_every_new_fact_round_trips_to_raw_source_with_utf8_byte_columns(self):
        self.build()
        with sqlite3.connect(self.destination/'.maintenance.sqlite3') as db:
            for raw, in db.execute('SELECT record FROM facts'):
                fact=json.loads(raw);loc=fact['source'];path=self.repo/loc['path']
                self.assertEqual(search.sha(path),loc['file_sha256'])
                lines=path.read_text().encode().splitlines(keepends=True)
                selected=lines[loc['start_line']-1:loc['end_line']]
                if len(selected)==1:
                    text=selected[0][loc['start_column']:loc['end_column']]
                else:
                    selected[-1]=selected[-1][:loc['end_column']]
                    selected[0]=selected[0][loc['start_column']:]
                    text=b''.join(selected)
                self.assertEqual(text.decode(),fact['text'])

    def test_match_source_association_and_changed_source_rejection(self):
        self.build()
        code,page,size=self.call('search','--query','"S"','--search-field','maintenance.annotations')
        row=page['items'][0]
        code,page,size=self.call('match',row['id'],'--ref',row['hit']['ref'])
        fact=page['items'][0]['context']
        self.assertEqual(page['items'][0]['value'][row['hit']['start']:row['hit']['end']],row['hit']['text'])
        self.assertEqual(self.call('source',row['id'],'--ref','maintenance:'+fact['id'])[0],0)
        self.assertEqual(self.call('source',row['id'],'--ref','maintenance:missing')[0],1)
        (self.repo/fact['source']['path']).write_text('changed')
        self.assertEqual(self.call('source',row['id'],'--ref','maintenance:'+fact['id'])[0],1)

    def test_cursor_binds_new_fact_database_and_public_helper(self):
        self.build()
        cursor=self.call('search','--limit','1')[1]['next_cursor']
        for name in ('.maintenance.sqlite3','maintenance_view.py'):
            path=self.destination/name;saved=path.read_bytes();path.write_bytes(saved+b'\n')
            code,result,_=self.call('search','--limit','1','--cursor',cursor)
            self.assertEqual(code,1)
            self.assertIn('STALE_OR_INVALID_CURSOR',result['message'])
            path.write_bytes(saved)

    def test_standalone_reader_readonly_caps_and_new_field_boolean_search(self):
        self.build();before=search.sha(self.destination/'.maintenance.sqlite3')
        run=subprocess.run(['python3',str(self.destination/'read.py'),'search','--query','factory','--search-field','maintenance.context_calls'],capture_output=True,text=True,cwd=self.root)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertFalse((self.destination/'__pycache__').exists())
        self.assertLessEqual(len(run.stdout.encode()),6000)
        self.assertEqual(before,search.sha(self.destination/'.maintenance.sqlite3'))
        self.assertEqual(self.call('search','--query','factory','--query','missing_value','--mode','and')[1]['matched_test_count'],0)
        self.assertEqual(self.call('search','--query','STATIC_FALLBACK','--search-field','maintenance.annotations')[1]['matched_test_count'],0)

    def test_context_caps_disclose_omissions_and_never_scan_unassociated_functions(self):
        path=self.repo/'tests/extra.py'
        path.write_text('def helper():\n'+''.join(f'    invoke_{i}()\n' for i in range(MAX_CALLS+3))+
                        '\ndef test_x():\n    pass\n\ndef unassociated():\n    secret_keyword()\n')
        extractor=Extractor(self.repo)
        result=extractor.describe('tests/extra.py::test_x',[('tests/extra.py::helper','calls')])
        self.assertEqual(len(result['facts']['context_calls']),MAX_CALLS)
        self.assertEqual(result['coverage']['skipped_context_calls'],3)
        self.assertFalse(any('secret_keyword' in extractor.facts[i]['text'] for ids in result['facts'].values() for i in ids))

    def test_ambiguous_external_and_cyclic_bases_terminate_with_unknowns(self):
        path=self.repo/'tests/cycle.py'
        path.write_text('class A(B): pass\nclass B(A):\n    def test_cycle(self): pass\nclass Outside(External):\n    def test_external(self): pass\n')
        extractor=Extractor(self.repo)
        cycle=extractor.describe('tests/cycle.py::B.test_cycle',[])
        facts=[extractor.facts[i] for i in cycle['facts']['inheritance']]
        self.assertEqual(len(facts),2)
        self.assertTrue(any('inheritance cycle candidate' in f['uncertainty'] for f in facts))
        external=extractor.describe('tests/cycle.py::Outside.test_external',[])
        self.assertEqual(extractor.facts[external['facts']['inheritance'][0]]['targets'],[])

    def test_changed_pure_base_is_rejected(self):
        (self.repo/'lib.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'Base source changed'):
            self.build()


if __name__=='__main__':
    unittest.main()
