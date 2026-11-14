"""Small offline acceptance: real sealing/ledger/scoring/viewer, fake Agent only."""
from __future__ import annotations
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from jsonschema import Draft202012Validator
from batch.core import BatchError, canonical_sha256, sha256_file, write_json
from batch.testcase_identity import inventory, resolve
from batch.testcase_labels import build_labels
from batch.testcase_metrics import measure, summarize, score, _raw_records
from batch.prepare import BENCH, _validate

BASE = 'a'*40
SOURCE = '''import pytest
class TestRequest:
    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_curl(self, method):
        assert method in ["GET", "POST"]

    def test_other(self):
        assert True

class TestOther:
    def test_curl(self):
        assert True

@pytest.fixture
def test_fixture():
    return 1

def helper():
    pass
'''
OLD = '''@pytest.mark.parametrize("method", ["GET", "POST"])
def test_curl(self, method):
    assert method in ["GET", "POST"]'''
NEW = OLD.replace('["GET", "POST"]', '["GET", "POST", "PUT"]')
IDENTITY = 'tests/test_request.py::TestRequest.test_curl'


def raw_record():
    return {'repo':'owner/repo','pr_id':42,'base_sha':BASE,'test_changes':[
        {'file':'tests/test_request.py','qualified_name':'TestRequest.test_curl','change_type':'modified',
         'old_test':OLD,'gold_test':NEW}]}


def candidate(symbol='TestRequest.test_curl'):
    return {'path':'tests/test_request.py','symbols':[symbol],'reason':'Task changes request formatting'}


class IdentityLabelsTests(unittest.TestCase):
    def test_index_and_paired_labels(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); (repo/'tests').mkdir(); (repo/'tests/test_request.py').write_text(SOURCE)
            index = inventory(repo, BASE)
            self.assertEqual(len(index['entries']),3)
            self.assertEqual(index,inventory(repo,BASE))
            self.assertNotIn('gold_test', json.dumps(index))
            self.assertNotIn('old_test', json.dumps(index))
            labels = build_labels(raw_record(),index)
            self.assertTrue(labels['complete']);self.assertEqual(labels['testcases'],[IDENTITY])
            raw = raw_record()
            raw['test_changes'] += [
                {'file':'tests/test_request.py','qualified_name':'test_new','change_type':'added'},
                {'file':'tests/test_request.py','qualified_name':'test_deleted','change_type':'deleted'},
                {'file':'tests/test_request.py','qualified_name':'helper','change_type':'modified'},
                {'file':'tests/test_request.py','qualified_name':'test_fixture','change_type':'modified',
                 'old_test':'@pytest.fixture\ndef test_fixture():\n    return 1','gold_test':'@pytest.fixture\ndef test_fixture():\n    return 2'},
                {'file':'tests/test_request.py','qualified_name':'TestRequest.test_other','change_type':'modified',
                 'old_test':'def test_other(self):\n    assert True',
                 'gold_test':'def test_other(self):\n    # formatting only\n    assert True'},
                {'file':'tests/test_request.py','qualified_name':'TestOther.test_curl','change_type':'modified',
                 'old_test':'def test_curl(self):\n    assert True', 'gold_test':'def test_renamed(self):\n    assert True'}]
            labels=build_labels(raw,index)
            self.assertTrue(labels['complete']);self.assertEqual(len(labels['testcases']),1)
            self.assertEqual(labels['excluded_counts'],{'added':1,'deleted':1,'helper_or_fixture':2,'mechanical_ast_equal':1,'renamed':1})
            raw['base_sha']='b'*40
            self.assertFalse(build_labels(raw,index)['complete'])
            for name,doc in [('testcase-index-v1',index),('host-testcase-labels-v1',labels)]:
                Draft202012Validator(json.loads((BENCH/'schemas'/f'{name}.schema.json').read_text())).validate(doc)

    def test_invalid_stale_and_ambiguous_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'tests').mkdir();(root/'tests/test_request.py').write_text(SOURCE)
            index=inventory(root,BASE)
            prediction=resolve([candidate('test_curl'),candidate('Wrong.test_curl'),candidate(),candidate()],index)
            self.assertEqual(prediction['testcases'],[IDENTITY]);self.assertEqual(len(prediction['invalid']),2);self.assertEqual(prediction['duplicate_count'],1)
            raw=raw_record();raw['test_changes'][0]['old_test']='def test_curl(self):\n    assert False'
            self.assertIn('OLD_SOURCE_MISMATCH',build_labels(raw,index)['issues'])
            (root/'tests/duplicate.py').write_text('def test_x(): pass\ndef test_x(): pass\n')
            with self.assertRaises(BatchError):inventory(root,BASE)

    def test_raw_source_hash_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);raw=root/'raw.jsonl';raw.write_text(json.dumps(raw_record())+'\n')
            plan=root/'plan.json';write_json(plan,{'inputs':{'raw':{'path':'raw.jsonl','sha256':sha256_file(raw)}},'tasks':[{'task_id':'task','repository':'owner/repo','pr_id':42}]})
            config={'approved_plan':{'path':'plan.json','sha256':sha256_file(plan)}}
            records,_=_raw_records(config,root);self.assertEqual(records['task'],raw_record())
            raw.write_text('{}\n')
            with self.assertRaises(BatchError) as e:_raw_records(config,root)
            self.assertEqual(e.exception.code,'PREPARE_INPUT_STALE')

    def test_method_fragments_preserve_multiline_string_indentation(self):
        source = 'class TestText:\n    def test_text(self):\n        value = """hello\n    preserve these spaces\n"""\n        assert value\n'
        fragment = '\n'.join(source.splitlines()[1:])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'tests').mkdir()
            (root / 'tests/test_text.py').write_text(source)
            index = inventory(root, BASE)
            raw = {'base_sha': BASE, 'test_changes': [{
                'file': 'tests/test_text.py', 'qualified_name': 'TestText.test_text',
                'change_type': 'modified', 'old_test': fragment,
                'gold_test': fragment.replace('hello', 'changed')} ]}
            labels = build_labels(raw, index)
            self.assertTrue(labels['complete'], labels['issues'])
            self.assertEqual(len(labels['testcases']), 1)


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);(root/'tests').mkdir();(root/'tests/test_request.py').write_text(SOURCE)
        self.index=inventory(root,BASE);self.labels=build_labels(raw_record(),self.index)

    def test_dual_metrics_and_false_positive_penalty(self):
        result=measure([candidate('TestOther.test_curl')],self.index,self.labels,protocol='testcase-v1',state='DETECT_SEALED')
        self.assertEqual(result['scoped_file']['f1'],1);self.assertEqual(result['testcase']['f1'],0)
        result=measure([candidate(),candidate('Missing.test_case')],self.index,self.labels,protocol='testcase-v1',state='DETECT_SEALED')
        self.assertEqual(result['testcase']['precision'],.5);self.assertAlmostEqual(result['testcase']['f1'],2/3)
        self.assertEqual(result['testcase']['invalid_count'],1)

    def test_empty_failure_history_no_positive_and_pending(self):
        def run(candidates,protocol='testcase-v1',state='DETECT_SEALED',labels=None):
            return measure(candidates,self.index,labels or self.labels,protocol=protocol,state=state)
        self.assertEqual(run([])['testcase']['f1'],0)
        failure=run(None,state='FAILED');self.assertEqual(failure['status'],'FAILED_ZERO')
        old=candidate();old['symbols']=[]
        self.assertEqual(run([old],'file-v1')['status'],'HISTORICAL_UNSCORABLE')
        self.assertEqual(run([],'file-v1')['status'],'HISTORICAL_UNSCORABLE')
        self.assertEqual(run([candidate()],'file-v1')['status'],'HISTORICAL_RESCORED')
        self.assertEqual(run(None,state='NOT_RECORDED')['status'],'PENDING')
        no_gold=dict(self.labels,testcases=[])
        self.assertEqual(run([candidate()],labels=no_gold)['false_alarm_count'],1)
        bad=dict(self.labels,complete=False)
        self.assertEqual(run([],labels=bad)['status'],'LABELS_INCOMPLETE')
        success=run([candidate()]);rows=[success,failure]
        self.assertEqual(summarize(rows,'testcase')['f1_macro'],.5)
        self.assertEqual(summarize(rows,'testcase',successful_only=True)['f1_macro'],1)


class FakeFlowTests(unittest.TestCase):
    def test_real_seal_metrics_and_dashboard_with_fake_agent(self):
        from batch import stages, testcase_metrics, experiment_cli
        from batch.orchestrator import Ledger, target_key
        from batch.result_view import build
        from batch.archive.viewer import module
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);bench=root/'sdd-bench/scrapy-sdd'
            shutil.copytree(BENCH/'schemas',bench/'schemas')
            (bench/'tools').mkdir();shutil.copy2(BENCH/'tools/sdd-results.py',bench/'tools/sdd-results.py')
            task_root=bench/'tasks/owner__repo__pr42';task_root.mkdir(parents=True)
            task={'task_id':task_root.name,'pr_id':42,'title':'Request formatting','baseline':{'base_sha':BASE}}
            task_path=task_root/'task.json';write_json(task_path,task)
            (task_root/'experiment-inputs').mkdir();(task_root/'experiment-inputs/task.md').write_text('Change request formatting')
            config={'schema_version':1,'batch_id':'fake-testcase','evaluation':{'kind':'detect-host','localization_protocol':'testcase-v1'},'tasks':[
                {'task_id':task_root.name,'task_manifest':{'path':task_path.relative_to(root).as_posix(),'sha256':sha256_file(task_path)},
                 'methods':[{'method':m,'detect':{'run_id':m+'-detect-1'},'updates':[]} for m in ('openspec','speckit','cc-sdd')]}]}
            config_path=bench/'batch/pilot/fake.json';write_json(config_path,config)
            repository=bench/'batch/baselines'/BASE/'repository';(repository/'tests').mkdir(parents=True)
            source=repository/'tests/test_request.py';source.write_text(SOURCE)
            files=[{'path':'tests/test_request.py','sha256':sha256_file(source)}]
            write_json(repository.parent/'baseline-lock.json',{'base_sha':BASE,'checkout_files':files,'checkout_manifest_sha256':canonical_sha256(files)})
            gold_path=bench/'batch/gold'/task_root.name/'gold-store.json'
            write_json(gold_path,{'store_type':'HOST_ONLY_GOLD','gold_target_files':['tests/test_request.py']})
            ledger=Ledger(bench/'batch/runs/fake-testcase/ledger.jsonl','fake-testcase',bench/'schemas/batch-ledger-event-v1.schema.json')
            before_gold=sha256_file(gold_path)
            prompts=[]
            def fake_agent(**kw):
                prompts.append(kw['prompt'])
                self.assertNotIn('gold_test',kw['prompt']);self.assertIn('fully qualified',kw['prompt'])
                out=kw['output'];(out/'agent.jsonl').write_text(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':10}})+'\n')
                from batch.token_usage import record_usage
                record_usage(out/'agent.jsonl',exit_code=0)
                (out/'rendered-compose.yaml').write_text('# fake, no runtime or gold mounts\n')
                planning=task_root/'runs'/kw['method']/'detect/planning-artifacts'
                write_json(planning/'detection-draft.json',{'candidates':[candidate()]})
                return sha256_file(out/'agent.jsonl'),sha256_file(out/'rendered-compose.yaml')
            targets = []
            for method in ('openspec','speckit','cc-sdd'):
                workspace=task_root/'runs'/method/'detect/workspace';shutil.copytree(repository,workspace)
                (workspace.parent/'planning-artifacts').mkdir()
                target={'task_id':task_root.name,'task_manifest':task_path,'method':method,'stage':'detect','mode':None,'run_id':method+'-detect-1','policy':None,'policy_sha256':None}
                out=workspace.parent/'executions'/target['run_id']/'attempt-1'
                targets.append(target)
            # Exercise the unified CLI and real coordinator, including protocol
            # forwarding, append-only ledger and the whole-batch Detect barrier.
            output = io.StringIO()
            frozen = {'prepared_id': 'fake-testcase'}
            with patch.object(stages,'_task_context',return_value=(task,task_root,BASE)), \
                 patch.object(stages,'_preflight_ready'), \
                 patch.object(stages,'_run_compose_agent',side_effect=fake_agent), \
                 patch.object(experiment_cli,'BENCH',bench), patch.object(experiment_cli,'ROOT',root), \
                 patch.object(experiment_cli,'_round_frozen',return_value=(frozen,config_path)), \
                 patch('batch.orchestrator.validate_prepared_manifest',return_value=(config,targets)), \
                 contextlib.redirect_stdout(output):
                code=experiment_cli.run(['run',str(config_path),'--round','offline','--stage','detect','--execute','--no-archive'])
            self.assertEqual(code,0,output.getvalue())
            self.assertTrue((bench/'batch/runs/fake-testcase/detect-barrier.json').is_file())
            view=build(config_path,bench,root)
            protected={p:sha256_file(p) for p in bench.rglob('*') if p.is_file()}
            with patch.object(testcase_metrics,'_raw_records',return_value=({task_root.name:raw_record()},[])):
                evaluated = io.StringIO()
                with patch.object(experiment_cli,'BENCH',bench), patch.object(experiment_cli,'ROOT',root), \
                     patch.object(experiment_cli,'_round_frozen',return_value=(frozen,config_path)), \
                     patch('batch.orchestrator.validate_prepared_manifest',return_value=(config,targets)), \
                     contextlib.redirect_stdout(evaluated):
                    code=experiment_cli.run(['evaluate',str(config_path),'--round','offline','--kind','testcase'])
                self.assertEqual(code,0,evaluated.getvalue())
                document=json.loads(evaluated.getvalue())['testcase_metrics']
                self.assertEqual(document['counts']['scored_count'],3,document['counts'])
                self.assertTrue(all(r['status']=='OK' for r in document['rows']),[(r['status'],r['error_code']) for r in document['rows']])
                self.assertTrue(all(r['testcase']['f1']==1 for r in document['rows']))
                self.assertEqual(document,testcase_metrics.compute(bench,'fake-testcase'))
            self.assertEqual(view['view_sha256'],document['result_view_sha256'])
            viewer=module(bench);html=viewer._testcase_table(bench,'fake-testcase')
            self.assertIn('testcase 级',html);self.assertIn('同范围文件级',html)
            self.assertIn('历史文件级',html)
            self.assertNotIn(IDENTITY,html);self.assertNotIn('gold_test',html)
            overview=next(e for e in viewer.discover(bench) if e.task_id_filter is None)
            current_targets=viewer.batch_targets(overview,bench)
            self.assertEqual(viewer.batch_token_usage(overview,current_targets,bench)['summary']['total_tokens'],330)
            self.assertIn('测试方法定位',viewer.build_html(overview,bench))
            from dataclasses import replace
            stale=viewer._testcase_table(bench,'fake-testcase',targets=[replace(t,attempt=2) for t in current_targets])
            self.assertIn('评分已过期',stale)
            self.assertNotIn('100.0%',stale)
            per_pr=next(e for e in viewer.discover(bench) if e.task_id_filter is not None)
            pr_html=viewer.build_html(per_pr,bench)
            self.assertIn('testcase 级',pr_html);self.assertIn('Token 用量',pr_html)
            self.assertEqual(sha256_file(gold_path),before_gold)
            self.assertEqual({p:sha256_file(p) for p in protected},protected)
            self.assertEqual(len(prompts),3)
            # Same sealed output is read-only; tampering is detected, not rescored.
            manifest=next(task_root.glob('runs/openspec/detect/executions/*/attempt-1/detection-manifest.json'))
            manifest.chmod(0o600);manifest.write_text('{}')
            with patch.object(testcase_metrics,'_raw_records',return_value=({task_root.name:raw_record()},[])):
                tampered=testcase_metrics.compute(bench,'fake-testcase')
            self.assertEqual(next(r for r in tampered['rows'] if r['method']=='openspec')['status'],'EVIDENCE_INVALID')

    def test_new_protocol_config_and_historical_contracts(self):
        from batch.rounds import compile_round
        path=BENCH/'batch/experiments/scrapy-3pr-testcase-v1.json'
        config=json.loads(path.read_text());_validate(config,'experiment-config-v2.schema.json')
        first=compile_round(path,'offline-check');second=compile_round(path,'offline-check')
        self.assertEqual(first['prepared_id'],second['prepared_id']);self.assertEqual(len(first['targets']),9)
        with tempfile.TemporaryDirectory(dir=BENCH) as td:
            old=Path(td)/'old.json';config['evaluation'].pop('localization_protocol');write_json(old,config)
            legacy=compile_round(old,'offline-check')
            self.assertNotEqual(legacy['prepared_id'],first['prepared_id'])
            self.assertEqual(legacy['targets'],first['targets'])


class PreparationTests(unittest.TestCase):
    def test_freeze_reuse_and_index_conflict_without_runtime(self):
        from batch import rounds
        from batch.prepare import _target
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);bench=root/'sdd-bench/scrapy-sdd';bench.mkdir(parents=True)
            rid='round-'+'c'*24;run=bench/'batch/runs'/rid
            ref=lambda p:{'path':p.relative_to(root).as_posix(),'sha256':sha256_file(p)}
            config=root/'config.json';write_json(config,{'test':True})
            source=root/'source.json';write_json(source,{})
            plan=root/'plan.json';write_json(plan,{})
            report=root/'report.json';write_json(report,{})
            original=root/'original.json';public={'task_id':'task-pr42','baseline':{'base_sha':BASE}};write_json(original,public)
            repository=bench/'batch/baselines'/BASE/'repository';(repository/'tests').mkdir(parents=True)
            (repository/'tests/test_request.py').write_text(SOURCE)
            files=[{'path':'tests/test_request.py','sha256':sha256_file(repository/'tests/test_request.py')}]
            lock=repository.parent/'baseline-lock.json';write_json(lock,{'base_sha':BASE,'checkout_files':files,'checkout_manifest_sha256':canonical_sha256(files)})
            image={'base_sha':BASE,'baseline_lock':ref(lock),'deployment_lock':ref(source),
                   'agent':{'tag':'fake','image_id':'sha256' + ':' + 'a'*64},'baseline':{'tag':'fake','image_id':'sha256' + ':' + 'a'*64}}
            evaluation={'kind':'detect-host','localization_protocol':'testcase-v1'}
            compiled={'config':{'experiment_id':'fake-testcase','evaluation':evaluation},'config_ref':ref(config),
                      'prepared_id':rid,'round_label':'offline','sources':[ref(source)],
                      'source_records':[{'source':ref(source),'plan_path':plan,'report_path':report,'approved_id':'fake'}],
                      'owners':{'task-pr42':({'task_manifest':ref(original)},{'baseline':{'base_sha':BASE}},ref(source))},
                      'images':[image],'targets':[_target('task-pr42','openspec','detect',None,'detect-1',BASE,ref(original),None)]}
            target=run/'tasks/task-pr42'
            def scaffold(**kw):
                target.mkdir(parents=True,exist_ok=True)
                if not (target/'task.json').exists():shutil.copyfile(original,target/'task.json')
            def audit(**kw):write_json(target/'isolation-audit.json',{'status':'PASS'})
            def preflight(**kw):write_json(target/'preflight-summary.json',{'status':'READY'})
            with patch.object(rounds,'compile_round',return_value=compiled),patch.object(rounds,'scaffold_tasks',side_effect=scaffold),patch.object(rounds,'run_audit',side_effect=audit),patch.object(rounds,'run_preflight',side_effect=preflight),patch.object(rounds,'_verify_task',side_effect=lambda *args:[ref(target/'task.json')]):
                frozen=rounds.prepare_round(config,'offline',root=root)
                self.assertEqual(set(frozen['testcase_indexes']),{BASE})
                index_path=root/frozen['testcase_indexes'][BASE]['path']
                self.assertFalse(index_path.is_relative_to(target))
                self.assertEqual(rounds.prepare_round(config,'offline',root=root),frozen)
                self.assertEqual((run/'ledger.jsonl').read_bytes(),b'')
                index_path.write_text('{}')
                with self.assertRaises(BatchError):rounds.load_round(run/'prepared-round.json',root=root,expected=compiled)
