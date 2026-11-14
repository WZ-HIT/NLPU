"""TI-24/25 isolation canaries and controller crash/stop/no-retry contracts."""
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'sdd-bench/scrapy-sdd'))
from batch.stages import detect_prompt,matched_material_prompt
from experiment.test_intention import matched_materials as materials,matched_pilot as pilot
from experiment.test_intention.compact import make_card
from experiment.test_intention import search_view as search,reader,maintenance_view as view
from experiment.test_intention.stage_b_bundle import write


class MaterialIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'parent';self.source.mkdir()
        self.identity='tests/test_x.py::test_x';self.canary='GENERATED_CANARY_f1abcc932'
        raw={'id':self.identity,'path':'tests/test_x.py',
             'source':{'id':self.identity,'path':'tests/test_x.py','start_line':1,'end_line':2},
             'contexts':[],'uncertainty':['pure static unknown'],'static':{'calls':[{'expression':'old_api()','line':2}],
             'assertions':[],'assignments':[],'conditions':[],'mock':[],'parameters':[],'dependency_links':[]}}
        semantic={'id':self.identity,'summary':self.canary,'inputs':[self.canary],'environment_mock':[],
                  'scenarios':[],'operations':[],'uncertainties':[self.canary]}
        card=make_card(dict(raw,semantic_status='GENERATED',intention=semantic))
        with sqlite3.connect(self.source/'.evidence.sqlite3') as db:
            db.executescript('''CREATE TABLE tests(id TEXT PRIMARY KEY,path TEXT,card TEXT,intention TEXT,facts TEXT,context_refs TEXT,uncertainty TEXT,location TEXT);
CREATE TABLE contexts(id TEXT PRIMARY KEY,metadata TEXT);
CREATE TABLE edges(source TEXT,target TEXT,relation TEXT,depth INTEGER,PRIMARY KEY(source,target,relation,depth));
CREATE TABLE files(path TEXT PRIMARY KEY,metadata TEXT);''')
            facts={k:v for k,v in raw['static'].items() if k!='dependency_links'}
            loc={k:v for k,v in raw['source'].items() if k!='id'}
            db.execute('INSERT INTO tests VALUES(?,?,?,?,?,?,?,?)',(self.identity,raw['path'],json.dumps(card),json.dumps(semantic),json.dumps(facts),'[]',json.dumps([*raw['uncertainty'],self.canary]),json.dumps(loc)))
            db.execute('INSERT INTO files VALUES(?,?)',(raw['path'],json.dumps({'path':raw['path'],'topic_samples':[self.canary],'summaries':'summaries/0000.jsonl','test_count':1})))
        with sqlite3.connect(self.source/'.maintenance.sqlite3') as db:
            db.executescript('CREATE TABLE facts(id TEXT,record TEXT);CREATE TABLE members(test_id TEXT,category TEXT,ordinal INT,fact_id TEXT);CREATE TABLE coverage(test_id TEXT,metadata TEXT);')
            db.execute('INSERT INTO coverage VALUES(?,?)',(self.identity,'{}'))
        directory=PROJECT/'experiment/test_intention'
        mapping={'read.py':'stage_b_reader.py','legacy_read.py':'reader.py'}
        for name in materials.CODE:shutil.copyfile(directory/mapping.get(name,name),self.source/name)
        write(self.source/'README.md',{});write(self.source/'relations.json',{});write(self.source/'index.json',{})
        m={'base_sha':'a'*40,'source_files':{},'maintenance_version':'maintenance-facts-v1',
           'files':{p.name:search.sha(p) for p in self.source.iterdir()}}
        write(self.source/'manifest.json',m)
        self.raw=self.root/'static.json';write(self.raw,{'base_sha':'a'*40,'source_files':{},'tests':[raw]})

    def test_no_semantic_canary_in_any_B_file_including_sqlite_pages(self):
        b=self.root/'B';c=self.root/'C'
        materials.export(self.source,self.raw,b,'B');materials.export(self.source,self.raw,c,'C')
        for path in b.rglob('*'):
            if path.is_file():self.assertNotIn(self.canary.encode(),path.read_bytes(),str(path))
        self.assertIn(self.canary.encode(),(c/'.evidence.sqlite3').read_bytes())
        with reader.connect(b) as db:
            row=db.execute('SELECT intention,uncertainty,card FROM tests').fetchone()
            self.assertIsNone(json.loads(row[0]));self.assertEqual(json.loads(row[1]),['pure static unknown'])
            self.assertEqual(json.loads(row[2])['status'],'STATIC_ONLY')
        docs,stats=search.load_index(b)
        self.assertFalse(view.rank(docs,stats,[self.canary]))
        docs,stats=search.load_index(c)
        self.assertEqual(len(view.rank(docs,stats,[self.canary])),1)
        for name in materials.CODE:self.assertEqual(search.sha(b/name),search.sha(c/name))

    def test_changed_static_provenance_rejected(self):
        raw=json.loads(self.raw.read_text());raw['source_files']={'other.py':'bad'};write(self.raw,raw)
        with self.assertRaisesRegex(ValueError,'provenance'):materials.export(self.source,self.raw,self.root/'B','B')

    def test_material_guidance_changes_only_availability(self):
        for method in pilot.METHODS:
            common=detect_prompt(method,'testcase-v1')
            self.assertIn('Prediction rule:',common)
            self.assertTrue((common+matched_material_prompt('B')).startswith(common))
            self.assertTrue((common+matched_material_prompt('C')).startswith(common))
        self.assertIn('STATIC_ONLY',matched_material_prompt('B'))
        self.assertNotIn('scenarios/detail as needed',matched_material_prompt('B'))
        self.assertIn('complete-only',matched_material_prompt('D'))
        with self.assertRaises(ValueError):matched_material_prompt('E')


class Controller(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.output=Path(self.tmp.name);self.root=self.output/'execution-root';self.bench=self.root/'sdd-bench/scrapy-sdd'
        (self.bench/'schemas').mkdir(parents=True)
        shutil.copyfile(PROJECT/'sdd-bench/scrapy-sdd/schemas/batch-ledger-event-v1.schema.json',self.bench/'schemas/batch-ledger-event-v1.schema.json')
        write(self.output/'execution-lock.json',{})
        write(self.output/'offline-acceptance.json',{'status':'PASS','execution_lock_sha256':search.sha(self.output/'execution-lock.json')})
        write(self.output/'authorization.json',{'target_limit':27,'budget_policy':'existing_balance_no_topup'})
        self.targets={};self.refs={};self.plan={'targets':[]}
        for group in 'ABC':
            run=self.bench/'batch/runs'/('round-'+group.lower()*24);run.mkdir(parents=True)
            self.refs[group]={'prepared_id':run.name,'manifest':str(run/'prepared-round.json')}
        for pi,pr in enumerate(pilot.PRS):
            for mi,method in enumerate(pilot.METHODS):
                order=list('ABC') if (pi+mi)%2==0 else list('CBA')
                for group in order:
                    task='scrapy__scrapy__pr'+str(pr)
                    manifest=Path(self.refs[group]['manifest']).parent/'tasks'/task/'task.json'
                    target={'task_id':task,'method':method,'task_manifest':manifest,'run_id':'detect-001','mode':None,'stage':'detect'}
                    self.targets[(group,task,method)]=({'batch_id':self.refs[group]['prepared_id']},target)
                    self.plan['targets'].append({'group':group,'task_id':task,'method':method})

    def invoke(self,fake):
        with patch.object(pilot,'prepared',return_value=(self.plan,self.refs,self.targets)),\
             patch.object(pilot,'check'),patch.object(pilot.first30,'execution_environment',return_value=(self.root,self.bench)),\
             patch('batch.stages.detect_targets',side_effect=fake),redirect_stdout(io.StringIO()):
            pilot.run(self.output)

    def test_one_start_across_resume_and_terminal_failure_preserved(self):
        calls=[]
        def fake(**kw):
            calls.append(str(kw['output']))
            if len(calls)==1:raise ValueError('simulated tool failure')
            return {'status':'SEALED'}
        self.invoke(fake);self.assertEqual(len(calls),27)
        states=pilot.Journal(self.output/'pilot-ledger.sqlite3').rows()
        self.assertEqual(sum(r['state']=='FAILED' for r in states.values()),1)
        self.invoke(fake);self.assertEqual(len(calls),27)
        self.assertTrue((self.output/'terminal-groups.json').exists())

    def test_interrupted_started_target_blocks_automatic_retry(self):
        pilot.Journal(self.output/'pilot-ledger.sqlite3').start(pilot.key(self.plan['targets'][0]))
        with self.assertRaisesRegex(ValueError,'Interrupted'):self.invoke(lambda **kw:self.fail('must not call'))

    def test_cross_process_claim_and_resume_never_duplicate_start(self):
        path=self.output/'pilot-ledger.sqlite3';identity=pilot.key(self.plan['targets'][0])
        script='import sys; from experiment.test_intention.matched_pilot import Journal; Journal(sys.argv[1]).start(sys.argv[2])'
        processes=[subprocess.Popen([sys.executable,'-c',script,str(path),identity],cwd=PROJECT,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        results=[p.communicate(timeout=15) for p in processes]
        self.assertEqual(sorted(p.returncode for p in processes),[0,1])
        self.assertTrue(any('ALREADY_STARTED_OR_TERMINAL' in err for out,err in results))
        self.assertEqual(pilot.Journal(path).rows()[identity]['starts'],1)
        with self.assertRaisesRegex(ValueError,'Interrupted'):self.invoke(lambda **kw:self.fail('must not call'))

    def test_budget_gate_missing_or_offline_barrier_failed_never_calls(self):
        write(self.output/'authorization.json',{'target_limit':270,'budget_policy':'existing_balance_no_topup'})
        with self.assertRaisesRegex(ValueError,'monetary'):self.invoke(lambda **kw:self.fail('must not call'))
        write(self.output/'authorization.json',{'target_limit':27,'budget_policy':'existing_balance_no_topup'})
        write(self.output/'offline-acceptance.json',{'status':'FAILED'})
        with self.assertRaisesRegex(ValueError,'acceptance'):self.invoke(lambda **kw:self.fail('must not call'))

    def test_balance_refusal_stops_new_dispatch_without_deadlock_or_retry(self):
        calls=[]
        def fake(**kw):
            calls.append(kw['output']);kw['output'].mkdir(parents=True)
            (kw['output']/'agent.jsonl').write_text('{"type":"error","message":"Insufficient Balance"}\n')
            raise ValueError('provider refused')
        self.invoke(fake)
        self.assertLessEqual(len(calls),3)
        rows=pilot.Journal(self.output/'pilot-ledger.sqlite3').rows()
        self.assertEqual(len(rows),27);self.assertTrue(all(r['state'] in pilot.TERMINAL for r in rows.values()))
        self.assertEqual(sum(r['starts'] for r in rows.values()),len(calls))

    def test_compare_cannot_read_labels_before_all_27_terminal(self):
        write(self.output/'terminal-groups.json',{'targets':{}})
        with patch.object(pilot,'prepared',return_value=(self.plan,self.refs,self.targets)):
            with self.assertRaisesRegex(ValueError,'27'):pilot.compare(self.output)


if __name__=='__main__':unittest.main()
