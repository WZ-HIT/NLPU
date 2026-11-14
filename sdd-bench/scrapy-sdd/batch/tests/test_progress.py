"""Progress counts are a read-only view, never a model or preparation action."""
import json
from pathlib import Path
import tempfile
import unittest

from batch.core import BatchError, sha256_file, write_json
from batch.orchestrator import Ledger
from batch.prepare import BENCH
from batch.progress import snapshot


class ProgressTests(unittest.TestCase):
    def test_counts_ignore_probe_resume_and_preserve_files(self):
        with tempfile.TemporaryDirectory() as td:
            bench=Path(td);(bench/'schemas').mkdir()
            schema=bench/'schemas/batch-ledger-event-v1.schema.json'
            schema.write_bytes((BENCH/'schemas'/schema.name).read_bytes())
            targets=[{'task_id':'task-pr1','method':method,'stage':'detect','run_id':'detect-1','mode':None} for method in ('openspec','speckit','cc-sdd')]
            compiled={'prepared_id':'round-test','config':{'experiment_id':'test'},'config_ref':{'path':'config.json','sha256':'a'*64},'targets':targets}
            run=bench/'batch/runs/round-test';run.mkdir(parents=True)
            write_json(run/'prepared-round.json',{'prepared_id':'round-test','experiment_id':'test','inputs':{'user_config':compiled['config_ref']},'target_count':3,'targets':targets})
            ledger=Ledger(run/'ledger.jsonl','round-test',schema)
            for t,state in zip(targets,('DETECT_SEALED','FAILED','DETECT_RUNNING')):
                ledger.append('detect',t,state,1,{})
            ledger.append('probe',targets[0],'DRY_RUN_READY',2,{})
            ledger.append('detect',targets[0],'SKIPPED_RESUME',1,{})
            before={p:sha256_file(p) for p in bench.rglob('*') if p.is_file()}
            result=snapshot(compiled,bench=bench)
            self.assertEqual([result[k] for k in ('total','sealed','failed','running','pending')],[3,1,1,1,0])
            self.assertIn('cc-sdd',result['active'][0])
            self.assertEqual(before,{p:sha256_file(p) for p in before})
            raw=(run/'ledger.jsonl').read_text();(run/'ledger.jsonl').write_text(raw.replace('DETECT_SEALED','DETECT_RUNNING',1))
            with self.assertRaises(BatchError):snapshot(compiled,bench=bench)

    def test_preparation_is_not_claimed_as_agent_completion(self):
        with tempfile.TemporaryDirectory() as td:
            bench=Path(td)
            compiled={'prepared_id':'round-test','config':{'experiment_id':'test'},'targets':[{}]*3}
            self.assertEqual(snapshot(compiled,bench=bench)['message'],'尚未开始')
            task=bench/'batch/runs/round-test/tasks/task-pr1'
            write_json(task/'preflight-summary.json',{'runtime_preflight_status':'READY'})
            result=snapshot(compiled,bench=bench)
            self.assertEqual(result['sealed'],0)
            self.assertIn('预检 READY 1',result['message'])
            self.assertEqual(result['pending'],3)
