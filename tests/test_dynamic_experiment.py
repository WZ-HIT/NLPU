"""D-only start limits, durable no-retry dispatch, and refusal stopping."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sdd-bench/scrapy-sdd'))
from experiment.test_intention import dynamic_experiment as driver,matched_completion as full,matched_pilot


class DDispatchTests(unittest.TestCase):
    def setUp(self):
        before={k:getattr(full,k) for k in ['OUTPUT','GROUPS','TOTAL','NEW','REUSED']}
        self.addCleanup(lambda:[setattr(full,k,v) for k,v in before.items()])
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.output=Path(self.tmp.name);self.root=self.output/'execution-root';self.bench=self.root/'sdd-bench/scrapy-sdd'
        (self.bench/'schemas').mkdir(parents=True)
        shutil.copyfile(ROOT/'sdd-bench/scrapy-sdd/schemas/batch-ledger-event-v1.schema.json',self.bench/'schemas/batch-ledger-event-v1.schema.json')
        driver.configure(self.output)
        full.write(self.output/'execution-lock.json',{})
        full.write(self.output/'authorization.json',{'groups':['D'],'target_limit':90,'budget_policy':'existing_balance_no_topup'})
        full.write(self.output/'offline-acceptance.json',{'status':'PASS','execution_lock_sha256':full.first30.sha(self.output/'execution-lock.json')})
        full.write(self.output/'reused-rows.json',{'source':'no reused predictions','groups':{'D':[]}})
        directory=self.bench/'batch/runs'/('round-'+'d'*24);directory.mkdir(parents=True)
        self.refs={'D':{'manifest':str(directory/'prepared-round.json'),'prepared_id':directory.name}}
        self.plan={'targets':[]};self.targets={}
        for pr in range(30):
            task='pr'+str(pr)
            for method in full.METHODS:
                row={'group':'D','task_id':task,'method':method,'pilot':False};self.plan['targets'].append(row)
                target={'task_id':task,'method':method,'stage':'detect','mode':None,'run_id':'detect-001',
                        'task_manifest':directory/'tasks'/task/'task.json'}
                self.targets[('D',task,method)]=({},target)

    def invoke(self,fake):
        with patch.object(full,'prepared',return_value=(self.plan,self.refs,self.targets)),patch.object(full,'check'),\
             patch.object(full.first30,'execution_environment',return_value=(self.root,self.bench)),\
             patch('batch.stages.detect_targets',side_effect=fake),redirect_stdout(io.StringIO()):
            full.run(self.output)

    def test_runs_exactly_90_d_once_and_no_reused_c(self):
        calls=[]
        self.invoke(lambda **kw:calls.append(kw['output']) or {'status':'SEALED'})
        state=full.status(self.output)
        self.assertEqual((len(calls),state['new_formal_starts'],state['terminal'],state['reused']),(90,90,90,0))
        self.invoke(lambda **kw:self.fail('No second attempt permitted'))

    def test_refusal_stops_remaining_dispatch_without_retries(self):
        calls=[]
        def fail(**kw):
            calls.append(kw['output']);raise RuntimeError('insufficient_balance')
        self.invoke(fail)
        self.assertLessEqual(len(calls),3)
        state=full.status(self.output)
        self.assertEqual(state['terminal'],90)
        self.assertGreater(state['states']['BLOCKED'],0)

    def test_rejects_broad_or_mismatched_authorization_before_any_provider(self):
        full.write(self.output/'authorization.json',{'groups':['C','D'],'target_limit':180,'budget_policy':'existing_balance_no_topup'})
        with self.assertRaisesRegex(ValueError,'authorization'):
            self.invoke(lambda **kw:self.fail('Out-of-scope call'))


if __name__=='__main__':unittest.main()
