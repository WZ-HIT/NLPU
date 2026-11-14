import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiment.test_intention.generation_contract import ContractError, OPTIONS, validate
from experiment.test_intention.recovery import Recovery, coordinator, body, make_plan, load_plan, sha, BeforeSendError, bind_plan
from experiment.test_intention.static import digest, write


def packet():
    return dict(version='test',tests=[dict(id='tests/a.py::test_a',source='def test_a(): assert 1 == 1',
                contexts=['app.py::helper'],uncertainty=[])],contexts=[dict(id='app.py::helper',source='def helper(): pass')])


def result(source=None):
    source=source or packet()
    return {'tests':[dict(id=t['id'],summary='Checks equality.',operations=['compare'],inputs=[],environment_mock=[],
            uncertainties=[],scenarios=[dict(conditions=[],actions=['compare'],expected=['equal'],evidence=[t['id']])])
            for t in source['tests']]}


def response(value=None, usage=True, status='completed'):
    text=json.dumps(value if value is not None else result())
    return dict(id='fake',model='deepseek-flash',status=status,
                usage={'input_tokens':100,'output_tokens':100} if usage else None,
                output=[dict(type='message',content=[dict(type='output_text',text=text)])])


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        source=packet();self.key=digest({'packet':source,'options':OPTIONS})
        self.plan=dict(workers=2,request_upper_bound=2,historical_accounting={'historical_formula_cost_cny':192.89},
             rows=[dict(new_key=self.key,old_key='old',packet=source,packet_sha256=digest(source),allowed_new_requests=2)])

    def runner(self,transport,budget=10):
        return Recovery(self.root/'run',self.plan,plan_hash='frozen',max_new_cny=budget,transport=transport)

    def test_reference_error_positions_and_peer_rules(self):
        source=packet();value=result(source)
        value['tests'][0]['scenarios'][0]['evidence']=[]
        with self.assertRaises(ContractError) as error:validate(value,source)
        self.assertEqual(error.exception.record['code'],'EVIDENCE_OWN_TEST_MISSING')
        self.assertEqual(error.exception.record['path'],'/tests/0/scenarios/0/evidence')
        source['tests'].append(dict(id='tests/a.py::test_b',contexts=['app.py::peer'],source='',uncertainty=[]))
        value=result(source);value['tests'][0]['scenarios'][0]['evidence'].append('app.py::peer')
        with self.assertRaises(ContractError) as error:validate(value,source)
        self.assertEqual(error.exception.record['code'],'EVIDENCE_PEER_CONTEXT')
        value['tests'][0]['scenarios'][0]['evidence'][-1]='invented:99'
        with self.assertRaises(ContractError) as error:validate(value,source)
        self.assertEqual(error.exception.record['code'],'EVIDENCE_NOT_SUPPLIED')

    def test_one_repair_then_reuse_without_more_calls(self):
        calls=[]
        def fake(payload,secret):
            calls.append(payload)
            return response({}) if len(calls)==1 else response()
        runner=self.runner(fake)
        self.assertEqual(runner.run()['states'],{'GENERATED':1})
        self.assertEqual(len(calls),2)
        initial=json.loads(calls[0]['input'])
        self.assertEqual(initial['tests'][0]['allowed_evidence_ids'],['tests/a.py::test_a','app.py::helper'])
        self.assertIn('ROOT_TESTS_ARRAY_REQUIRED',calls[1]['input'])
        self.runner(fake).run();self.assertEqual(len(calls),2)
        self.assertTrue((self.root/'run/results'/f'{self.key}.json').exists())

    def test_unknown_cost_survives_restart_and_is_not_retried(self):
        calls=[]
        def fail(*args):calls.append(1);raise TimeoutError()
        runner=self.runner(fail);status=runner.run()
        self.assertEqual(status['states'],{'COST_UNKNOWN':1})
        self.assertGreater(status['new_unknown_spend_reservation_cny'],0)
        restarted=self.runner(fail);self.assertEqual(restarted.run()['new_request_count'],1)
        self.assertEqual(len(calls),1)

    def test_budget_rejection_has_snapshot_and_cannot_be_reset(self):
        fake=unittest.mock.Mock(side_effect=AssertionError('must not send'))
        runner=self.runner(fake,budget=.00001)
        status=runner.run();self.assertEqual(status['new_request_count'],0)
        self.assertEqual(status['states'],{'NOT_SENT_BUDGET':1})
        with runner.db() as db:
            detail=json.loads(db.execute("SELECT detail FROM events WHERE kind='BUDGET_REJECTED'").fetchone()[0])
        self.assertIn('NEW_COST_LIMIT',detail['triggers']);self.assertIn('at',detail)
        self.assertIn('accounted_and_reserved_micro_cny',detail)
        with self.assertRaisesRegex(ValueError,'budget changed'):self.runner(fake,budget=10)

    def test_missing_usage_invalid_response_blocks_paid_repair(self):
        calls=[]
        def fake(*args):calls.append(1);return response({},usage=False)
        runner=self.runner(fake);status=runner.run()
        self.assertEqual(status['states'],{'HOLD':1});self.assertEqual(len(calls),1)
        self.assertGreater(status['new_unknown_spend_reservation_cny'],0)

    def test_crash_after_response_save_recovers_without_resending(self):
        fake=unittest.mock.Mock(return_value=response())
        runner=self.runner(fake)
        with patch.object(runner,'account',side_effect=RuntimeError('simulated crash')):
            with self.assertRaisesRegex(RuntimeError,'simulated crash'):runner.run()
        restarted=self.runner(fake)
        self.assertEqual(restarted.run()['states'],{'GENERATED':1})
        self.assertEqual(fake.call_count,1)
        self.assertEqual(restarted.snapshot()['new_unknown_spend_reservation_cny'],0)

    def test_complete_invalid_outputs_stop_after_one_repair(self):
        fake=unittest.mock.Mock(return_value=response({}))
        runner=self.runner(fake)
        self.assertEqual(runner.run()['states'],{'FALLBACK':1})
        self.runner(fake).run();self.assertEqual(fake.call_count,2)

    def test_incomplete_output_does_not_auto_retry(self):
        fake=unittest.mock.Mock(return_value=response(status='incomplete'))
        self.assertEqual(self.runner(fake).run()['states'],{'FALLBACK':1})
        self.assertEqual(fake.call_count,1)

    def test_concurrent_coordinator_is_rejected(self):
        runner=self.runner(unittest.mock.Mock(return_value=response()))
        with coordinator(self.root/'run'):
            with self.assertRaisesRegex(RuntimeError,'ALREADY_RUNNING'):runner.run()

    def test_known_pre_send_failure_is_not_unknown_spend(self):
        runner=self.runner(unittest.mock.Mock(side_effect=BeforeSendError('missing credential')))
        status=runner.run();self.assertEqual(status['states'],{'HOLD':1})
        self.assertEqual(status['new_accounted_or_reserved_cny'],0)
        self.assertEqual(status['new_unknown_spend_reservation_cny'],0)

    def test_same_plan_cannot_start_in_another_output_or_reset_allowance(self):
        directory=self.root/'plan';write(directory/'plan.json',self.plan)
        bind_plan(directory,self.root/'execution',200)
        bind_plan(directory,self.root/'execution',200)
        with self.assertRaisesRegex(ValueError,'PLAN_ALREADY_BOUND'):
            bind_plan(directory,self.root/'another-execution',200)
        with self.assertRaisesRegex(ValueError,'PLAN_ALREADY_BOUND'):
            bind_plan(directory,self.root/'execution',300)

    def test_repair_inputs_have_explicit_bounds(self):
        with self.assertRaisesRegex(ValueError,'REPAIR_INPUT_LIMIT'):
            body(packet(),'x'*65537,{})
        with self.assertRaisesRegex(ValueError,'REPAIR_ERROR_LIMIT'):
            body(packet(),'{}',{'detail':'x'*5000})

    def test_whole_packet_and_source_identity_preserved(self):
        source=packet();value=result(source)
        value['tests'][0]['id']='foreign'
        with self.assertRaises(ContractError):validate(value,source)
        with self.assertRaises(ContractError):validate({'tests':[]},source)
        source['tests'].append(dict(source['tests'][0],id='tests/a.py::test_b'))
        with self.assertRaises(ContractError):validate(result(),source)


class PlanTests(unittest.TestCase):
    def test_repartition_incomplete_reuse_success_and_freeze_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);original=root/'original';audit=root/'audit'
            source=packet();second=copy.deepcopy(source['tests'][0]);second['id']='tests/a.py::test_b'
            incomplete=dict(source,tests=[*source['tests'],second])
            metadata=[]
            for name,source_packet,state,why in [('ok',source,'GENERATED','GENERATED'),
                    ('bad',incomplete,'STATIC_FALLBACK','OUTPUT_INCOMPLETE')]:
                path=original/'cache'/f'{name}.json'
                write(path,dict(packet=source_packet,options={'legacy':True},status=state,
                      result=result(source_packet) if state=='GENERATED' else None,attempts=[]))
                metadata.append(dict(cache_path=str(path),cache_sha256=sha(path),cache_key=name,status=state,
                    base_shas=['a','b'],versioned_test_records=2*len(source_packet['tests']),reason=why,request_journal_ids=[]))
            write(original/'scope.json',{'base_shas':['a','b']})
            write(audit/'packets.json',metadata);write(audit/'requests.json',[])
            write(audit/'coverage.json',[]);write(audit/'sources.json',{'sha256':{}})
            write(audit/'summary.json',dict(status='PASS',accounting={}))
            write(audit/'coverage-groups.json',[{'group':'a','group_type':'base'},{'group':'b','group_type':'base'}])
            plan=make_plan(audit,original,root/'plan')
            self.assertEqual(plan['reused_successful_packets'],1)
            self.assertEqual(plan['historical_failed_packet_count'],1)
            self.assertEqual(plan['recovery_packet_count'],2)
            self.assertEqual(plan['expected_restored_versioned_records'],4)
            self.assertEqual(plan['request_upper_bound'],4)
            self.assertTrue(all(len(row['packet']['tests'])==1 for row in plan['rows']))
            load_plan(root/'plan')
            path=Path(plan['reuse'][0]['cache_path']);path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'cache changed'):load_plan(root/'plan')
