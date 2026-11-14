import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from experiment.test_intention.compact import export_base
from experiment.test_intention.reader import main, page


class CompactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'canonical';self.dest=self.root/'workspace/test-intentions'
        self.source.mkdir();(self.source/'tests').mkdir()
        self.repo=self.dest.parent
        self.context={'id':'helpers.py::fixture','path':'helpers.py','start_line':1,'end_line':2,'kind':'function','source':'def fixture():\n    return 3\n'}
        self.test={'id':'tests/test_x.py::test_x','path':'tests/test_x.py','source':{'id':'tests/test_x.py::test_x','path':'tests/test_x.py','start_line':1,'end_line':2,'source':'def test_x():\n    assert True\n'},'semantic_status':'GENERATED','uncertainty':[], 'contexts':[self.context],
            'static':{'assertions':[{'expression':'True','line':2}], 'calls':[], 'dependency_links':[{'source':'tests/test_x.py::test_x','target':'helpers.py::fixture','relation':'uses_fixture','depth':1}]*2},
            'intention':{'id':'tests/test_x.py::test_x','summary':'Checks the returned value.','inputs':['a'], 'operations':['fixture'], 'environment_mock':[], 'uncertainties':[],
                'scenarios':[{'conditions':['condition '+str(i)+'x'*600], 'actions':['call'], 'expected':['expected '+str(i)], 'evidence':['tests/test_x.py::test_x','helpers.py::fixture']} for i in range(3)]}}
        self.put('tests/00000.json',self.test)
        other=json.loads(json.dumps(self.test));other['id']='tests/test_x.py::test_unknown';other['source']['id']=other['id'];other['semantic_status']='STATIC_FALLBACK';other['intention']=None;other['static']['dependency_links']=[]
        self.put('tests/00001.json',other)
        self.put('README.md',{})
        self.put('index.json',{})
        self.put('relations.json',[])
        files={p.relative_to(self.source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.rglob('*') if p.is_file()}
        self.put('manifest.json',{'base_sha':'a'*40,'files':files,'source_files':{}})

    def put(self,name,value):
        (self.source/name).write_text(json.dumps(value))

    def read(self,*args):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=main(list(args),self.dest,self.repo)
        return code,json.loads(output.getvalue()),output.getvalue()

    def test_identity_scenarios_evidence_and_no_source_duplication(self):
        stats=export_base(self.source,self.dest)
        self.assertEqual(stats['tests'],2);self.assertEqual(stats['unique_contexts'],1);self.assertEqual(stats['unique_edges'],1)
        db=sqlite3.connect(self.dest/'.evidence.sqlite3')
        self.assertEqual({r[0] for r in db.execute('SELECT id FROM tests')},{self.test['id'],'tests/test_x.py::test_unknown'})
        self.assertEqual(json.loads(db.execute('SELECT intention FROM tests WHERE id=?',(self.test['id'],)).fetchone()[0]),self.test['intention'])
        contexts=json.loads(db.execute('SELECT metadata FROM contexts').fetchone()[0]);self.assertNotIn('source',contexts)
        card=json.loads(db.execute('SELECT card FROM tests WHERE id=?',(self.test['id'],)).fetchone()[0])
        self.assertEqual(card['scenarios']['more'],3)
        unknown=json.loads(db.execute('SELECT card FROM tests WHERE id=?',('tests/test_x.py::test_unknown',)).fetchone()[0]);self.assertIsNone(unknown['goal']);self.assertEqual(unknown['status'],'STATIC_FALLBACK')
        db.close()
        code,result,text=self.read('search','--query','expected 2');self.assertEqual(code,0);self.assertEqual(result['items'][0]['id'],self.test['id'])
        code,result,text=self.read('scenarios',self.test['id']);self.assertEqual(len(result['items']),3)
        (self.repo/'tests').mkdir();(self.repo/'tests/test_x.py').write_text(self.test['source']['source']);(self.repo/'helpers.py').write_text(self.context['source'])
        code,result,text=self.read('source',self.test['id'],'--ref',self.context['id']);self.assertEqual(code,0);self.assertEqual(len(result['items']),2)
        code,result,text=self.read('source',self.test['id'],'--ref','../private');self.assertEqual(code,1)
        before=hashlib.sha256((self.dest/'.evidence.sqlite3').read_bytes()).hexdigest();self.read('show',self.test['id']);self.assertEqual(before,hashlib.sha256((self.dest/'.evidence.sqlite3').read_bytes()).hexdigest())

    def test_pagination_never_loses_oversize_record_and_respects_bytes(self):
        value={'conditions':['长文本'*3000],'expected':['value']};offset=0;fragments=[]
        while True:
            result=page([value],offset,25,4096);self.assertLessEqual(len((json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n').encode()),4096)
            fragments.extend(result['items']);offset=result['next_offset']
            if offset is None:break
        self.assertEqual(json.loads(''.join(p['text'] for p in fragments)),value)

    def test_changed_canonical_evidence_is_rejected(self):
        (self.source/'tests/00000.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Canonical bundle changed'):export_base(self.source,self.dest)


if __name__=='__main__':unittest.main()
