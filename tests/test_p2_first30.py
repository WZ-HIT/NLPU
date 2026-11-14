import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiment.test_intention import p2_first30 as runner


class P2RoundTests(unittest.TestCase):
    def test_failed_no_positive_is_not_correct_empty(self):
        rows=[{'status':'NO_POSITIVE_GOLD','state':'FAILED','false_alarm_count':0},
              {'status':'NO_POSITIVE_GOLD','state':'DETECT_SEALED','false_alarm_count':0},
              {'status':'NO_POSITIVE_GOLD','state':'DETECT_SEALED','false_alarm_count':2},
              {'status':'FAILED_ZERO','state':'FAILED'}]
        self.assertEqual(runner.no_positive_categories(rows),
            {'run_failed':1,'success_correct_empty':1,'success_false_alarm':1})

    def test_incomplete_terminal_barrier_never_opens_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for states in ({'only-one':'DETECT_SEALED'}, {str(i):'DETECT_SEALED' if i else 'DETECT_RUNNING' for i in range(90)}):
                (root/'terminal-targets.json').write_text(json.dumps({'target_count':90,'states':states}))
                with patch.object(runner,'runtime_check'),patch.object(runner.first30,'execution_environment',side_effect=AssertionError('must not enter evaluation')):
                    with self.assertRaisesRegex(ValueError,'All 90'):
                        runner.compare(root)

    def test_status_retains_running_failures_and_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest=root/'round/prepared-round.json';manifest.parent.mkdir()
            (root/'execution-status.json').write_text('{"stage":"run","state":"RUNNING"}')
            (root/'prepared-reference.json').write_text(json.dumps({'prepared_id':'round-test','manifest':str(manifest)}))
            events=[{'target':{'task_id':str(i),'method':'openspec'},'state':state} for i,state in enumerate(('DETECT_SEALED','FAILED','DETECT_RUNNING'))]
            (manifest.parent/'ledger.jsonl').write_text('\n'.join(map(json.dumps,events))+'\n')
            status=runner.status(root)
            self.assertEqual(status['completed'],2)
            self.assertEqual(status['pending'],87)
            self.assertEqual(status['targets']['DETECT_RUNNING'],1)

    def test_frozen_controller_tamper_stops_before_model_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'execution-root/controller.py';source.parent.mkdir();source.write_text('original')
            (root/'controller-lock.json').write_text(json.dumps({'files':{'controller.py':runner.first30.sha(source)}}))
            with patch.object(runner.pilot,'runtime_check'):
                runner.runtime_check(root)
                source.write_text('changed')
                with self.assertRaisesRegex(ValueError,'Frozen controller changed'):
                    runner.runtime_check(root)


if __name__=='__main__':
    unittest.main()
