"""Offline usage accounting and dashboard compatibility; synthetic logs only."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from jsonschema import Draft202012Validator

from batch.core import BatchError, canonical_sha256, sha256_file, write_json
from batch.prepare import BENCH
from batch.token_usage import aggregate, read_usage, record_usage


def completed(inputs=100, outputs=10, **extra):
    return {'type':'turn.completed','usage':{'input_tokens':inputs,'output_tokens':outputs,**extra}}


def write_log(path, events):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(event)+'\n' for event in events))


class TokenParserTests(unittest.TestCase):
    def test_turn_totals_do_not_double_count_cache_reasoning_or_cumulative_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            log=Path(td)/'agent.jsonl'
            event=completed(cached_input_tokens=80, reasoning_output_tokens=4,cache_write_input_tokens=0)
            write_log(log,[{'type':'turn.started'},event,{'type':'token_count','total_token_usage':{'total_tokens':999999}},
                           {'type':'turn.started'},event])
            result=read_usage(log)
            self.assertEqual(result['total_tokens'],220)
            self.assertEqual(result['input_tokens'],200)
            self.assertEqual(result['cached_input_tokens'],160)
            self.assertEqual(result['reasoning_output_tokens'],8)
            self.assertEqual(result['status'],'RECORDED')
            self.assertEqual(result['completed_turn_count'],2)
            result['input_tokens']=0
            self.assertEqual(read_usage(log)['input_tokens'],200)

    def test_missing_zero_and_partial_are_different(self):
        with tempfile.TemporaryDirectory() as td:
            log=Path(td)/'agent.jsonl'
            self.assertIsNone(read_usage(log)['total_tokens'])
            write_log(log,[{'type':'turn.failed','error':{'message':'not echoed'}}])
            self.assertIsNone(read_usage(log)['total_tokens'])
            write_log(log,[completed(0,0)])
            self.assertEqual(read_usage(log)['total_tokens'],0)
            self.assertEqual(read_usage(log)['status'],'RECORDED')
            write_log(log,[completed(cached_input_tokens=None)])
            self.assertEqual(read_usage(log)['total_tokens'],110)
            self.assertIsNone(read_usage(log)['cached_input_tokens'])
            write_log(log,[completed(cached_input_tokens=9999)])
            self.assertEqual(read_usage(log)['total_tokens'],110)
            self.assertEqual(read_usage(log)['status'],'PARTIAL')
            write_log(log,[{'type':'turn.started'},completed(),{'type':'turn.started'},{'type':'turn.failed'}])
            self.assertEqual(read_usage(log)['status'],'PARTIAL')
            self.assertEqual(read_usage(log)['total_tokens'],110)
            write_log(log,[completed(),completed(input_tokens=True)])
            # bool is invalid; do not invent numeric counts.
            result=read_usage(log)
            self.assertEqual(result['total_tokens'],110)
            self.assertEqual(result['invalid_event_count'],1)
            with log.open('a') as f:f.write('{"truncated":')
            self.assertEqual(read_usage(log)['status'],'PARTIAL')

    def test_record_is_numeric_private_and_schema_valid(self):
        with tempfile.TemporaryDirectory() as td:
            log=Path(td)/'agent.jsonl'
            write_log(log,[{'type':'item.completed','item':{'text':'PRIVATE_PROMPT_SECRET_GOLD'}},completed()])
            record=record_usage(log,exit_code=0)
            self.assertNotIn('PRIVATE_PROMPT_SECRET_GOLD',json.dumps(record))
            schema=json.loads((BENCH/'schemas/agent-token-usage-v1.schema.json').read_text())
            Draft202012Validator(schema).validate(record)
            self.assertEqual(record['source']['sha256'],sha256_file(log))
            payload=dict(record);digest=payload.pop('usage_sha256')
            self.assertEqual(digest,canonical_sha256(payload))
            with self.assertRaises((BatchError,FileExistsError)):
                record_usage(log,exit_code=0)

    def test_aggregate_retains_unknown_coverage_and_optional_fields(self):
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'a/agent.jsonl';b=Path(td)/'b/agent.jsonl'
            write_log(a,[completed(cached_input_tokens=50)])
            write_log(b,[completed(20,2)])
            values=[read_usage(a),read_usage(b),read_usage(Path(td)/'missing')]
            total=aggregate(values)
            self.assertEqual(total['total_tokens'],132)
            self.assertEqual(total['status'],'PARTIAL')
            self.assertEqual(total['missing_attempt_count'],1)
            self.assertIsNone(total['cached_input_tokens'])

    def test_failed_real_runner_records_usage_before_raising(self):
        from batch.stages import _run_compose_agent
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);bench=root/'bench';out=root/'attempt';out.mkdir()
            runtime=bench/'environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates'
            catalog=runtime/'model-catalogs/deepseek-flash/models.json';write_json(catalog,{})
            import shutil
            shutil.copytree(Path(__file__).resolve().parents[1] / 'public_detect', bench / 'batch/public_detect',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            data=''.join(json.dumps(e)+'\n' for e in [completed(),{'type':'turn.failed'}])
            responses=[subprocess.CompletedProcess([],0,'services: {}\n'),subprocess.CompletedProcess([],0),
                       subprocess.CompletedProcess([],1,data,'fake failure'),subprocess.CompletedProcess([],0)]
            with patch('batch.stages.subprocess.run',side_effect=responses):
                with self.assertRaises(BatchError):
                    _run_compose_agent(task_root=root,bench=bench,method='openspec',stage='detect',run_id='run-1',mode=None,
                                       env={},prompt='public task',output=out,override=None)
            record=json.loads((out/'token-usage.json').read_text())
            self.assertEqual(record['total_tokens'],110)
            self.assertEqual(record['status'],'PARTIAL')
            self.assertEqual(record['process_exit_code'],1)


class TokenViewerTests(unittest.TestCase):
    def test_retry_failure_probe_and_resume_accounting_and_read_only_dashboard(self):
        from tests.test_sdd_detect_metrics import MetricsFixture
        from batch.archive.viewer import module
        with tempfile.TemporaryDirectory() as td:
            fixture=MetricsFixture(Path(td))
            fixture.fail_detect('openspec',attempt=1)
            fixture.seal_detect(attempt=2)
            write_log(fixture.execution('openspec',1)/'agent.jsonl',[completed(20,5,cached_input_tokens=10)])
            write_log(fixture.execution('openspec',2)/'agent.jsonl',[completed(100,10,cached_input_tokens=80)])
            # Orphan files and non-formal probe events must not inflate usage.
            write_log(fixture.execution('openspec',3)/'agent.jsonl',[completed(9999,9999)])
            target={'task_id':fixture.TASK_ID,'method':'openspec','stage':'detect','run_id':fixture.run_id('openspec'),'mode':None}
            fixture.ledger.append('probe',target,'DRY_RUN_READY',3,{'probe':True})
            fixture.ledger.append('detect',target,'SKIPPED_RESUME',2,{'resume':True})
            viewer=module(fixture.bench)
            exp=next(e for e in viewer.discover(fixture.bench) if e.task_id_filter is None)
            targets=viewer.batch_targets(exp,fixture.bench)
            before={p:sha256_file(p) for p in fixture.bench.rglob('*') if p.is_file()}
            usage=viewer.batch_token_usage(exp,targets,fixture.bench)
            self.assertEqual(usage['summary']['total_tokens'],135)
            self.assertEqual(usage['summary']['attempt_count'],2)
            self.assertEqual(usage['rows'][0]['state'],'FAILED')
            html=viewer._usage_table(usage)
            self.assertIn('135',html);self.assertIn('attempt 1',html);self.assertIn('FAILED',html)
            self.assertIn('历史实验',viewer.dashboard_html([exp],fixture.bench))
            self.assertIn('Token 用量',viewer.build_html(exp,fixture.bench))
            self.assertEqual(before,{p:sha256_file(p) for p in before})
            (fixture.execution('openspec',1)/'agent.jsonl').unlink()
            usage=viewer.batch_token_usage(exp,targets,fixture.bench)
            self.assertEqual(usage['summary']['status'],'PARTIAL')
            self.assertEqual(usage['summary']['total_tokens'],110)
            self.assertEqual(usage['summary']['missing_attempt_count'],1)

    def test_update_modes_are_separate_and_legacy_phase_logs_work(self):
        from batch.archive.viewer import module
        from tests.test_sdd_detect_metrics import MetricsFixture
        with tempfile.TemporaryDirectory() as td:
            fixture=MetricsFixture(Path(td));viewer=module(fixture.bench)
            config=json.loads(fixture.config_path.read_text())
            config['tasks'][0]['methods'][0]['updates']=[{'run_id':'update-1','mode':'self-directed'},{'run_id':'update-1','mode':'sealed-detect'}]
            write_json(fixture.config_path,config)
            for mode,n in [('self-directed',30),('sealed-detect',50)]:
                target={'task_id':fixture.TASK_ID,'method':'openspec','stage':'update','run_id':'update-1','mode':mode}
                fixture.ledger.append('update',target,'FAILED',1,{'failed':True})
                log=fixture.task_root/'runs/openspec/update/executions/update-1/attempt-1'/f'mode-{mode}/artifacts/agent.jsonl'
                write_log(log,[completed(n,5)])
            exp=next(e for e in viewer.discover(fixture.bench) if e.task_id_filter is None)
            usage=viewer.batch_token_usage(exp,viewer.batch_targets(exp,fixture.bench),fixture.bench)
            self.assertEqual(usage['summary']['total_tokens'],90)
            self.assertEqual({r['mode'] for r in usage['rows']},{'self-directed','sealed-detect'})
            legacy=Path(td)/'legacy';write_log(legacy/'cc-sdd/phases/01-plan.jsonl',[completed(40,4)])
            old=viewer.Experiment('old',legacy,'old',0)
            self.assertEqual(viewer._legacy_token_usage(old)['summary']['total_tokens'],44)

    def test_missing_and_corrupt_testcase_reports_offer_host_command(self):
        from batch.archive.viewer import module
        from tests.test_sdd_detect_metrics import MetricsFixture
        with tempfile.TemporaryDirectory() as td:
            fixture=MetricsFixture(Path(td));viewer=module(fixture.bench)
            html=viewer._testcase_table(fixture.bench,fixture.BATCH_ID)
            self.assertIn('尚未生成双粒度评分',html)
            self.assertIn('--testcase',html)
            self.assertNotIn('0.0%',html)
            bad={'metric_definition_version':'detect-metrics-v3','rows':[],'methods':[]}
            bad['metric_set_sha256']=canonical_sha256(bad)
            write_json(fixture.bench/'Log/reports/testcase-metrics'/f'{fixture.BATCH_ID}.json',bad)
            html=viewer._testcase_table(fixture.bench,fixture.BATCH_ID)
            self.assertIn('校验失败',html)
