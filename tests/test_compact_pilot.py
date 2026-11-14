import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from experiment.test_intention import first30
from experiment.test_intention.compact_pilot import aggregate, runtime_check


class CompactPilotTests(unittest.TestCase):
    def test_nine_targets_durable_start_hook_and_failure_preservation(self):
        from batch.orchestrator import Ledger, _latest, target_key
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);root=out/'execution-root';bench=root/'sdd-bench/scrapy-sdd';schemas=bench/'schemas';schemas.mkdir(parents=True)
            shutil.copyfile('sdd-bench/scrapy-sdd/schemas/batch-ledger-event-v1.schema.json',schemas/'batch-ledger-event-v1.schema.json')
            rid='round-'+'a'*24;runroot=bench/'batch/runs'/rid;runroot.mkdir(parents=True)
            manifest=runroot/'prepared-round.json';manifest.write_text('{}')
            (out/'prepared-reference.json').write_text(json.dumps({'manifest':str(manifest)}))
            targets=[{'task_id':f'fake-pr{i}','method':m,'stage':'detect','run_id':'detect-1','mode':None,'task_manifest':runroot/f'tasks/fake-pr{i}/task.json'} for i in range(3) for m in ('openspec','speckit','cc-sdd')]
            (out/'scope.json').write_text(json.dumps({'targets':[{'task_id':t['task_id'],'method':t['method']} for t in targets]}))
            starts=[];called=[]
            def hook(target):starts.append(target_key(target))
            def fake_detect(**kwargs):
                identity=(kwargs['task_manifest'].parent.name,kwargs['method'])
                target=next(t for t in targets if (t['task_id'],t['method'])==identity)
                key=target_key(target)
                latest=_latest(Ledger(runroot/'ledger.jsonl',rid,schemas/'batch-ledger-event-v1.schema.json').read())
                self.assertEqual(latest[key]['state'],'DETECT_RUNNING');self.assertIn(key,starts);called.append(key)
                if identity==('fake-pr0','speckit'):raise ValueError('synthetic failure')
                return {'state':'SEALED'}
            with patch.object(first30,'execution_environment',return_value=(root,bench)),patch('batch.orchestrator.validate_prepared_manifest',return_value=({'batch_id':rid},targets)),patch('batch.stages.detect_targets',side_effect=fake_detect),contextlib.redirect_stdout(io.StringIO()):
                first30.run(out,expected_count=9,before_detect=hook)
            terminal=json.loads((out/'terminal-targets.json').read_text())
            self.assertEqual(len(called),9);self.assertEqual(len(set(called)),9)
            self.assertEqual(list(terminal['states'].values()).count('FAILED'),1)
            self.assertEqual(list(terminal['states'].values()).count('DETECT_SEALED'),8)
            self.assertTrue((runroot/'execution-events/fake-pr0-speckit-FAILED.json').exists())

    def test_old_report_is_filtered_before_aggregation(self):
        from batch.testcase_metrics import summarize
        ids={(f'pr{i}',m) for i in range(3) for m in ('openspec','speckit','cc-sdd')}
        rows=[]
        for i in range(30):
            for method in ('openspec','speckit','cc-sdd'):
                rows.append({'task_id':f'pr{i}','method':method,'status':'OK','state':'DETECT_SEALED',
                    'testcase':{'tp':1,'fp':0,'fn':0,'predicted_count':1,'gold_count':1,'invalid_count':0,'precision':1.,'recall':1.,'f1':1.}})
        full_ids={(r['task_id'],r['method']) for r in rows}
        full=aggregate({'batch_id':'fake','rows':rows},full_ids,summarize)
        self.assertEqual(len(full['rows']),90)
        self.assertTrue(all(m['testcase']['scored_count']==30 for m in full['methods']))
        result=aggregate({'batch_id':'fake','rows':rows},ids,summarize)
        self.assertEqual(len(result['rows']),9)
        self.assertTrue(all(m['testcase']['scored_count']==3 for m in result['methods']))
        rows[0]['status']='EVIDENCE_INVALID'
        with self.assertRaisesRegex(ValueError,'Invalid evaluation evidence'):aggregate({'batch_id':'fake','rows':rows},ids,summarize)

    def test_runtime_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);root=out/'execution-root';root.mkdir();path=root/'config.toml';path.write_text('fixed')
            (out/'runtime-lock.json').write_text(json.dumps({'files':{'config.toml':first30.sha(path)},'model':'deepseek-flash','effort':'high','rollout_limit_tokens':100000}))
            runtime_check(out);path.write_text('changed')
            with self.assertRaisesRegex(ValueError,'configuration changed'):runtime_check(out)


if __name__=='__main__':unittest.main()
