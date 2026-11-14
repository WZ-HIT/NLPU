import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiment.test_intention import continue_codex_generation as controller
from experiment.test_intention.continue_codex_generation import (
    next_action,ledger_state,read_quota,recovery_decision,transport_evidence,
    transient_account_error,
)
from experiment.test_intention.codex_recovery import CodexRecovery,OPTIONS
from experiment.test_intention.static import digest


class ContinuationTests(unittest.TestCase):
    def test_active_worker_is_observed_without_duplicate_start(self):
        self.assertEqual(next_action(None,True),'OBSERVE_WORKER')
        self.assertEqual(next_action({'states':{'PENDING':772}},True),'OBSERVE_WORKER')

    def test_only_quota_exhaustion_is_automatically_resumed(self):
        self.assertEqual(next_action({'states':{'GENERATED':20,'PENDING':752},'stop_reason':'SUBSCRIPTION_LIMIT_NEAR'},False),'CHECK_QUOTA')
        self.assertEqual(next_action({'states':{'PENDING':752},'stop_reason':'CLI_FAILURE_USAGE_UNKNOWN'},False),'NEEDS_DIAGNOSIS')
        self.assertEqual(next_action({'states':{'PENDING':752},'stop_reason':None},False),'NEEDS_DIAGNOSIS')
        self.assertEqual(next_action({'states':{'GENERATED':770,'FALLBACK':2}},False),'PREPARE_REVIEW')

    def fixture(self,root):
        execution=root/'execution';execution.mkdir()
        with sqlite3.connect(execution/'ledger.sqlite3') as db:
            db.execute('CREATE TABLE packets(key TEXT PRIMARY KEY,state TEXT,detail TEXT)')
            db.execute('CREATE TABLE requests(id TEXT,key TEXT,attempt INTEGER,state TEXT,body_sha TEXT,response_sha TEXT,created TEXT)')
            db.execute('INSERT INTO packets VALUES(?,?,?)',('failed','COST_UNKNOWN',json.dumps({'exception_type':'TimeoutError'})))
            db.execute('INSERT INTO packets VALUES(?,?,?)',('pending','PENDING','{}'))
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)',('request','failed',1,'COST_UNKNOWN','body',None,'2026-11-06T00:00:00Z'))
        folder=execution/'cli'/'invocation';folder.mkdir(parents=True)
        (folder/'launch.json').write_text(json.dumps({'payload_sha256':'body'}))
        (folder/'stderr.log').write_text('stream disconnected before completion: request timed out')
        (folder/'events.jsonl').write_text('{"type":"thread.started","thread_id":"example"}\n')
        log=root/'worker.log';log.write_text('{"stop_reason":"CLI_TIMEOUT_USAGE_UNKNOWN"}\n')
        return execution,folder,log

    def test_transport_recovery_is_read_only_and_requires_matching_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            execution,folder,log=self.fixture(Path(temporary))
            before=(execution/'ledger.sqlite3').read_bytes()
            state=ledger_state(execution)
            evidence=transport_evidence(execution,state,'CLI_TIMEOUT_USAGE_UNKNOWN',log)
            self.assertEqual(evidence['packet_state'],'COST_UNKNOWN')
            self.assertEqual(evidence['request_id'],'request')
            self.assertEqual(before,(execution/'ledger.sqlite3').read_bytes())
            (folder/'launch.json').write_text(json.dumps({'payload_sha256':'another request'}))
            self.assertIsNone(transport_evidence(execution,state,'CLI_TIMEOUT_USAGE_UNKNOWN',log))

    def test_open_requests_tools_and_fatal_errors_never_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            execution,folder,log=self.fixture(Path(temporary));state=ledger_state(execution)
            self.assertIsNone(transport_evidence(execution,{**state,'open_requests':1},'CLI_TIMEOUT_USAGE_UNKNOWN',log))
            (folder/'events.jsonl').write_text(json.dumps({'item':{'type':'command_execution'}})+'\n')
            self.assertIsNone(transport_evidence(execution,state,'CLI_TIMEOUT_USAGE_UNKNOWN',log))
            (folder/'events.jsonl').write_text('')
            log.write_text('ValueError: Plan source changed\n')
            self.assertIsNone(transport_evidence(execution,state,'CLI_TIMEOUT_USAGE_UNKNOWN',log))
            log.write_text('status\n')
            self.assertIsNone(transport_evidence(execution,state,'UNEXPECTED_TOOL_USE',log))
            self.assertIsNone(transport_evidence(execution,state,'CLI_TIMEOUT_USAGE_UNKNOWN',log,worker_failed=True))

    def test_pre_send_rpc_error_is_recoverable_but_auth_error_is_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            execution,folder,log=self.fixture(Path(temporary));state=ledger_state(execution)
            log.write_text('RuntimeError: Account RPC failed: -32603\n')
            evidence=transport_evidence(execution,state,None,log,worker_failed=True)
            self.assertEqual(evidence['code'],'PRE_SEND_ACCOUNT_RPC_ERROR')
        self.assertTrue(transient_account_error(RuntimeError('Account RPC failed: -32603')))
        self.assertFalse(transient_account_error(RuntimeError('ChatGPT login required, API route refused')))

    def test_quota_rpc_process_is_closed_even_if_enter_fails(self):
        with patch.object(controller,'RateClient') as factory:
            factory.return_value.__enter__.side_effect=TimeoutError('Account RPC timeout')
            with self.assertRaises(TimeoutError):read_quota()
            factory.return_value.__exit__.assert_called_once()

    def test_backoff_is_persistent_and_three_failures_without_progress_stop(self):
        first=recovery_decision({},dict(signature='a'),458,100)
        self.assertEqual(first['action'],'TRANSPORT_BACKOFF')
        self.assertEqual(first['retry_at'],160)
        again=recovery_decision(json.loads(json.dumps(first)),dict(signature='a'),458,161)
        self.assertEqual(again['consecutive'],1)
        self.assertEqual(again['action'],'CHECK_QUOTA')
        second=recovery_decision(again,dict(signature='b'),458,200)
        self.assertEqual(second['retry_at'],500)
        third=recovery_decision(second,dict(signature='c'),458,600)
        self.assertEqual(third['action'],'NEEDS_DIAGNOSIS')
        progress=recovery_decision(second,dict(signature='c'),459,600)
        self.assertEqual(progress['consecutive'],1)

    def test_read_only_rpc_errors_do_not_consume_generation_failure_allowance(self):
        transport=recovery_decision({},dict(signature='timeout'),458,100)
        rpc=recovery_decision(transport,dict(signature='rpc',code='PRE_SEND_ACCOUNT_RPC_ERROR'),458,200)
        self.assertEqual(rpc['consecutive'],1)
        self.assertEqual(rpc['retry_at'],260)
        another_transport=recovery_decision(rpc,dict(signature='another-timeout'),458,300)
        self.assertEqual(another_transport['consecutive'],2)

    def test_real_worker_continues_next_packet_without_retrying_unknown_packet(self):
        rows=[]
        for i in range(3):
            identity=f'tests/a.py::test_{i}'
            source=dict(tests=[dict(id=identity,source=f'def test_{i}(): assert True',contexts=[],uncertainty=[])],contexts=[])
            rows.append(dict(new_key=digest({'packet':source,'options':OPTIONS}),old_key=f'old{i}',
                             packet=source,packet_sha256=digest(source),allowed_new_requests=2))
        plan=dict(backend='codex-subscription',options=OPTIONS,workers=1,request_upper_bound=6,historical_accounting={},rows=rows)
        class Transport:
            stop_reason=None
            calls=[]
            def __call__(self,payload,secret):
                self.calls.append(payload)
                if len(self.calls)==1:
                    self.stop_reason='CLI_TIMEOUT_USAGE_UNKNOWN';raise TimeoutError()
                identity=rows[1]['packet']['tests'][0]['id']
                semantic=dict(id=identity,summary='Asserts truth.',operations=['assert'],inputs=[],environment_mock=[],
                    uncertainties=[],scenarios=[dict(conditions=[],actions=['assert'],expected=['true'],evidence=[identity])])
                return dict(id='fake',model=OPTIONS['model'],status='completed',usage={'input_tokens':100,'output_tokens':100},
                    output=[dict(type='message',content=[dict(type='output_text',text=json.dumps({'tests':[semantic]}))])])
        class Rates:
            def limits(self):return {'rateLimits':{'primary':{'usedPercent':0}}}
        with tempfile.TemporaryDirectory() as temporary:
            transport=Transport();runner=CodexRecovery(Path(temporary),plan,plan_hash='same',max_new_cny=0,transport=transport)
            self.assertEqual(runner.run_subscription(Rates())['states'],{'COST_UNKNOWN':1,'PENDING':2})
            transport.stop_reason=None
            result=runner.run_subscription(Rates(),limit=1)
            self.assertEqual(result['states'],{'COST_UNKNOWN':1,'GENERATED':1,'PENDING':1})
            self.assertEqual(result['new_request_count'],2)
            self.assertEqual(len(transport.calls),2)

    def test_controller_survives_quota_rpc_error_and_waits_before_pending_only_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);execution,folder,log=self.fixture(root)
            output=root/'continuation';output.mkdir();(output/'worker.log').write_text(log.read_text())
            plan=root/'plan';plan.mkdir();(plan/'plan.json').write_text('{}')
            (execution/'status.json').write_text(json.dumps({'states':{'COST_UNKNOWN':1,'PENDING':1},'stop_reason':'CLI_TIMEOUT_USAGE_UNKNOWN'}))
            epoch=[100]
            def sleep(seconds):epoch[0]+=seconds
            def worker(command,control,record):
                self.assertIn('experiment.test_intention.codex_recovery',command)
                with sqlite3.connect(execution/'ledger.sqlite3') as db:
                    self.assertEqual(db.execute("select state from packets where key='failed'").fetchone()[0],'COST_UNKNOWN')
                    db.execute("update packets set state='GENERATED' where key='pending'")
                (execution/'status.json').write_text(json.dumps({'states':{'GENERATED':1,'COST_UNKNOWN':1},'stop_reason':None}))
                return 0
            def sample(command,**kwargs):
                self.assertIn('sample',command)
                quality=root/'quality';quality.mkdir();(quality/'review.json').write_text('{"decision":"NOT_REVIEWED"}')
                return SimpleNamespace(returncode=0)
            args=['continue','--plan',str(plan),'--execution',str(execution),'--output',str(output),
                  '--current',str(root/'current'),'--resume-transient-errors']
            with patch.object(controller.sys,'argv',args), \
                 patch.object(controller,'load_plan',return_value={'backend':'codex-subscription','options':OPTIONS}), \
                 patch.object(controller,'active',return_value=False), \
                 patch.object(controller.time,'time',side_effect=lambda:epoch[0]), \
                 patch.object(controller.time,'sleep',side_effect=sleep), \
                 patch.object(controller,'read_quota',side_effect=[TimeoutError('Account RPC timeout'),
                    {'rateLimits':{'primary':{'usedPercent':95}}},{'rateLimits':{'primary':{'usedPercent':0}}}]) as quota, \
                 patch.object(controller,'run_worker',side_effect=worker) as run, \
                 patch.object(controller.subprocess,'run',side_effect=sample):
                controller.main()
            self.assertEqual(quota.call_count,3)
            self.assertEqual(run.call_count,1)
            self.assertEqual(json.loads((output/'status.json').read_text())['state'],'READY_FOR_SOURCE_QUALITY_REVIEW')
            self.assertEqual(json.loads((root/'quality/review.json').read_text())['decision'],'NOT_REVIEWED')

    def test_fatal_worker_error_cannot_reuse_stale_quota_stop_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);execution,folder,log=self.fixture(root)
            output=root/'continuation';output.mkdir();(output/'worker.log').write_text(log.read_text())
            plan=root/'plan';plan.mkdir();(plan/'plan.json').write_text('{}')
            (execution/'status.json').write_text(json.dumps({'states':{'PENDING':1},'stop_reason':'SUBSCRIPTION_LIMIT_NEAR'}))
            def worker(command,control,record):
                (output/'worker.log').write_text('ValueError: Plan source changed\n')
                return 1
            args=['continue','--plan',str(plan),'--execution',str(execution),'--output',str(output),
                  '--current',str(root/'current'),'--resume-transient-errors']
            with patch.object(controller.sys,'argv',args), \
                 patch.object(controller,'load_plan',return_value={'backend':'codex-subscription','options':OPTIONS}), \
                 patch.object(controller,'active',return_value=False), \
                 patch.object(controller,'read_quota',return_value={'rateLimits':{'primary':{'usedPercent':0}}}), \
                 patch.object(controller,'run_worker',side_effect=worker) as run:
                controller.main()
            self.assertEqual(run.call_count,1)
            self.assertEqual(json.loads((output/'status.json').read_text())['state'],'NEEDS_DIAGNOSIS')
