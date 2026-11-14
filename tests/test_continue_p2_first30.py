import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

continuation=importlib.import_module('experiment.test_intention.continue_p2_first30')


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'execution-status.json').write_text('{"stage":"prepare","state":"COMPLETED"}')
        manifest=self.root/'round/prepared-round.json';manifest.parent.mkdir();manifest.write_text('{}')
        (manifest.parent/'ledger.jsonl').write_text('')
        (self.root/'prepared-reference.json').write_text(json.dumps({'manifest':str(manifest)}))
        target=self.root/'execution-root/experiment/test_intention/p2_first30.py';target.parent.mkdir(parents=True);target.write_text('old')
        candidate=self.root/'controller-candidate/p2_first30.py';candidate.parent.mkdir();candidate.write_text('frozen candidate')
        (candidate.parent/'metadata.json').write_text(json.dumps({'sha256':continuation.sha(candidate)}))
        (self.root/'controller-lock.json').write_text('{"files":{}}')

    def invoke(self):
        with patch.object(continuation,'OUTPUT',self.root),patch('sys.argv',['continuation','--prepare-pid','999999999','--prepare-start','0']),patch.object(continuation.os,'chdir') as change,patch.object(continuation.os,'execv') as execute:
            continuation.main()
            return change,execute

    def test_success_runs_only_frozen_workflow_after_preparation(self):
        change,execute=self.invoke()
        self.assertEqual(execute.call_count,1)
        self.assertEqual(execute.call_args.args[1][-2:],['experiment.test_intention.p2_first30','workflow'])
        change.assert_called_once_with(self.root/'execution-root')
        lock=json.loads((self.root/'controller-lock.json').read_text())
        self.assertEqual(lock['revision'],2)
        self.assertEqual(lock['files']['experiment/test_intention/p2_first30.py'],continuation.sha(self.root/'controller-candidate/p2_first30.py'))

    def test_failed_preparation_does_not_start_model(self):
        (self.root/'execution-status.json').write_text('{"stage":"prepare","state":"FAILED"}')
        with self.assertRaisesRegex(RuntimeError,'Preparation did not complete'):
            self.invoke()
        self.assertEqual(json.loads((self.root/'automation-status.json').read_text())['state'],'FAILED')

    def test_formal_attempt_prevents_controller_revision(self):
        (self.root/'round/ledger.jsonl').write_text('existing formal attempt\n')
        with self.assertRaisesRegex(RuntimeError,'Existing formal attempts'):
            self.invoke()

    def test_candidate_tampering_prevents_model_start(self):
        (self.root/'controller-candidate/p2_first30.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'Candidate controller changed'):
            self.invoke()


if __name__=='__main__':unittest.main()
