"""B contracts: provenance, bounded notes, interrupted saves, and safe replay parsing."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sdd-bench/scrapy-sdd'))
from batch.public_detect import decisions, judgment
from batch.stages import detect_prompt
from batch.scaffold import METHODS
from experiment.test_intention import sensitivity_view, reader, stage_b_reader, search_view
from experiment.test_intention.stage_b_offline import searches
from experiment.test_intention.decision_diagnostics import export as export_decisions


class Decisions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';(self.repo/'tests').mkdir(parents=True)
        (self.repo/'tests/test_a.py').write_text('def test_value():\n    assert 1 == 1\n')
        self.directory=self.root/'planning'
        self.record={'id':'tests/test_a.py::test_value','task_requirement':'Change expected value',
            'state':'pending','edit_scope':'method_content','method_edit_reason':'Need to check expectation',
            'support':['tests/test_a.py:2'], 'against':[], 'unknowns':['New value unspecified'],
            'exposure':{'stage':'source_expanded','refs':['tests/test_a.py:1-2']}}

    def test_shared_rules_and_planning_paths(self):
        for method,settings in METHODS.items():
            prompt=detect_prompt(method,'testcase-v1')
            self.assertIn(judgment.RULE.format(planning=settings['planning_mount_path']),prompt)
            self.assertIn('decisions.py save',prompt)
        self.assertNotIn('decisions.py',detect_prompt('openspec','file-v1'))

    def test_success_exclusion_history_and_final_draft_separate(self):
        result=decisions.save(self.directory,self.record,self.repo);self.assertTrue(result['saved'])
        self.assertFalse((self.directory/'detection-draft.json').exists())
        self.record['state']='excluded';self.record['edit_scope']='helper_only'
        decisions.save(self.directory,self.record,self.repo)
        state=json.loads(decisions.store_path(self.directory).read_text())
        record=state['records'][self.record['id']]
        self.assertEqual(record['revision'],2);self.assertEqual(record['history'][0]['state'],'pending')
        self.assertEqual(record['record']['edit_scope'],'helper_only')

    def test_repeated_and_excessive_updates(self):
        decisions.save(self.directory,self.record,self.repo)
        self.assertTrue(decisions.save(self.directory,self.record,self.repo)['unchanged'])
        for i in (2,3):
            self.record['method_edit_reason']=f'New evidence {i}'
            self.assertEqual(decisions.save(self.directory,self.record,self.repo)['revision'],i)
        self.record['method_edit_reason']='Fourth update'
        with self.assertRaisesRegex(ValueError,'UPDATE_LIMIT'):decisions.save(self.directory,self.record,self.repo)

    def test_interrupted_atomic_replace_preserves_prior(self):
        decisions.save(self.directory,self.record,self.repo)
        path=decisions.store_path(self.directory);before=path.read_bytes()
        self.record['state']='excluded'
        with patch('batch.public_detect.contract.os.replace',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):decisions.save(self.directory,self.record,self.repo)
        self.assertEqual(path.read_bytes(),before)

    def test_rejects_invalid_identity_enum_scope_and_size(self):
        for field,value in [('id','tests/test_a.py::test_missing'),('state','sure'),('task_requirement','x'*241)]:
            record=copy.deepcopy(self.record);record[field]=value
            self.assertFalse(decisions.save(self.directory,record,self.repo)['saved'])
        record=copy.deepcopy(self.record);record['state']='selected';record['edit_scope']='helper_only'
        self.assertEqual(decisions.issues(record)[0]['code'],'SELECTED_REQUIRES_METHOD_SUPPORT')
        record=copy.deepcopy(self.record);record['state']='selected';record['support']=[]
        self.assertFalse(decisions.save(self.directory,record,self.repo)['saved'])
        record=copy.deepcopy(self.record);record['exposure']['refs']=[]
        self.assertFalse(decisions.save(self.directory,record,self.repo)['saved'])

    def test_symlink_cannot_write_outside_planning(self):
        elsewhere=self.root/'elsewhere';elsewhere.mkdir()
        self.directory.symlink_to(elsewhere,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'SYMLINK'):decisions.save(self.directory,self.record,self.repo)
        self.assertEqual(list(elsewhere.iterdir()),[])

    def test_diagnostics_distinguish_failed_selected_excluded_and_unknown(self):
        self.assertEqual(export_decisions(self.directory)['coverage'],'UNKNOWN')
        self.record['state']='selected'
        decisions.save(self.directory,self.record,self.repo)
        self.assertEqual(export_decisions(self.directory,run_state='FAILED')['rows'][0]['diagnostic_stage'],'SELECTED_RUN_FAILED')
        self.assertEqual(export_decisions(self.directory)['rows'][0]['diagnostic_stage'],'SELECTED_OUTPUT_UNKNOWN')
        self.record['state']='excluded';self.record['against']=['Helper-only change suffices']
        decisions.save(self.directory,self.record,self.repo)
        result=export_decisions(self.directory,{'candidates':[]},'DETECT_SEALED')
        self.assertEqual(result['rows'][0]['diagnostic_stage'],'EXPANDED_EXCLUDED_REPORTED')
        self.assertIsNone(result['rows'][0].get('exclusion_causality'))


class SourcePoints(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';(self.repo/'tests').mkdir(parents=True)
        self.source=self.repo/'tests/test_a.py';self.source.write_text('def test_a():\n    assert f("ä") == 3\n')
        self.bundle=self.root/'bundle';self.bundle.mkdir()
        (self.bundle/'manifest.json').write_text(json.dumps({'source_files':{'tests/test_a.py':search_view.sha(self.source)}}))
        self.identity='tests/test_a.py::test_a'
        self.fact={'expression':'f("ä")','line':2,'name':'f','status':'unresolved','targets':[]}
        location={'path':'tests/test_a.py','start_line':1,'end_line':2}
        with sqlite3.connect(self.bundle/'.evidence.sqlite3') as db:
            db.execute('create table tests(id text,card text,intention text,facts text,context_refs text,uncertainty text,location text)')
            db.execute('insert into tests values(?,?,?,?,?,?,?)',(self.identity,'{}','null',json.dumps({'calls':[self.fact]}),'[]','[]',json.dumps(location)))
        with sqlite3.connect(self.bundle/'.maintenance.sqlite3') as db:
            db.execute('create table coverage(test_id text,metadata text)')
            db.execute('create table facts(id text,record text)')
            db.execute('create table members(test_id text,category text,ordinal int,fact_id text)')
            db.execute('insert into coverage values(?,?)',(self.identity,'{}'))

    def test_point_restores_fact_and_source_without_classifying_constructor(self):
        with reader.connect(self.bundle) as db:
            points,_=sensitivity_view.points(self.bundle,db,self.identity)
            self.assertEqual(len(points),1);self.assertEqual(points[0]['kind'],'api_or_construction_call')
            result=sensitivity_view.expand(self.bundle,db,self.identity,'/facts/calls/0',self.repo)[0]
        self.assertEqual(result['original_fact'],self.fact)
        self.assertEqual(result['source_lines'],[{'line':2,'source':'    assert f("ä") == 3'}])
        self.assertIn('start line only',result['source_extent'])

    def test_changed_source_unknown_ref_and_symlink_rejected(self):
        with reader.connect(self.bundle) as db:
            with self.assertRaisesRegex(ValueError,'NOT_ASSOCIATED'):sensitivity_view.expand(self.bundle,db,self.identity,'/facts/calls/999',self.repo)
            self.source.write_text('different\n')
            with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):sensitivity_view.expand(self.bundle,db,self.identity,'/facts/calls/0',self.repo)
            target=self.root/'outside';self.source.rename(target);self.source.symlink_to(target)
            with self.assertRaisesRegex(ValueError,'UNSAFE'):sensitivity_view.expand(self.bundle,db,self.identity,'/facts/calls/0',self.repo)

    def test_cli_short_page_and_expand_are_bounded(self):
        for argv in (['sensitive',self.identity],['point',self.identity,'--ref','/facts/calls/0']):
            stdout=io.StringIO()
            with redirect_stdout(stdout):code=stage_b_reader.main(argv,self.bundle,self.repo)
            self.assertEqual(code,0);self.assertLessEqual(len(stdout.getvalue().encode()),6000)
            self.assertIn('items',json.loads(stdout.getvalue()))

    def test_actual_reader_startup_does_not_write_bundle_bytecode(self):
        source=ROOT/'experiment/test_intention'
        for name,target in [('stage_b_reader.py','read.py'),('reader.py','legacy_read.py'),
                            ('sensitivity_view.py','sensitivity_view.py'),('maintenance_view.py','maintenance_view.py'),
                            ('search_view.py','search_view.py')]:
            shutil.copyfile(source/name,self.bundle/target)
        before={p.relative_to(self.bundle) for p in self.bundle.rglob('*')}
        process=subprocess.run([sys.executable,str(self.bundle/'read.py'),'--help'],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual({p.relative_to(self.bundle) for p in self.bundle.rglob('*')},before)


class ReplayParser(unittest.TestCase):
    def test_literal_wrapped_multiple_and_filtered_queries(self):
        result,failures=searches('/bin/bash -c \'python3 read.py search --query "a b" --mode and; python3 read.py search --query c --search-field maintenance.imports\'')
        self.assertFalse(failures);self.assertEqual(len(result),2)
        self.assertEqual(result[0]['queries'],['a b']);self.assertEqual(result[0]['mode'],'and')
        self.assertEqual(result[1]['selected'],['maintenance.imports'])

    def test_dynamic_or_unsupported_stays_unknown_without_execution(self):
        for command in ('python3 read.py search --query "$a"','python3 read.py search --query x --bad y','python3 read.py search --query `secret`'):
            queries,errors=searches(command);self.assertFalse(queries);self.assertTrue(errors)
        queries,errors=searches('python3 read.py show a')
        self.assertEqual((queries,errors),([],[]))


if __name__=='__main__':unittest.main()
