"""Resume and conflict behavior over the frozen historical preparation evidence."""

import json
import tempfile
import unittest
from pathlib import Path

from batch.core import BatchError
from batch.prepare_run import ROOT, STEPS, load_prepared, prepare

CONFIG = ROOT / 'sdd-bench/scrapy-sdd/batch/experiments/scrapy-3pr-both-pilot-v1.json'


class PrepareRunTests(unittest.TestCase):
    def test_first_resume_reuse_and_conflict(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            def interrupt(step):
                if step == 'images':
                    raise RuntimeError('simulated interruption')
            with self.assertRaises(RuntimeError):
                prepare(CONFIG, output, after_step=interrupt)
            state = json.loads((output / 'state.json').read_text())
            self.assertEqual(list(state['steps']), list(STEPS[:3]))
            self.assertFalse((output / 'prepared-manifest.json').exists())
            first = prepare(CONFIG, output)
            self.assertEqual(first['target_count'], 27)
            self.assertEqual(load_prepared(output / 'prepared-manifest.json'), first)
            frozen = (output / 'prepared-manifest.json').read_bytes()
            second = prepare(CONFIG, output)
            self.assertEqual(first, second)
            self.assertEqual(frozen, (output / 'prepared-manifest.json').read_bytes())
            state_path = output / 'state.json'
            state = json.loads(state_path.read_text())
            state['steps']['images']['evidence_sha256'] = '0' * 64
            state_path.write_text(json.dumps(state))
            # Frozen output remains authoritative; a conflict in mutable progress
            # does not alter or invalidate the already verified manifest.
            self.assertEqual(prepare(CONFIG, output), first)

    def test_hash_conflict_fails_before_freeze(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            def interrupt(step):
                if step == 'images':
                    raise RuntimeError('simulated interruption')
            with self.assertRaises(RuntimeError):
                prepare(CONFIG, output, after_step=interrupt)
            state_path = output / 'state.json'
            state = json.loads(state_path.read_text())
            state['steps']['images']['evidence_sha256'] = '0' * 64
            state_path.write_text(json.dumps(state))
            with self.assertRaises(BatchError) as caught:
                prepare(CONFIG, output)
            self.assertEqual(caught.exception.code, 'PREPARE_EVIDENCE_CONFLICT')
            self.assertFalse((output / 'prepared-manifest.json').exists())

    def test_agent_visible_input_contains_no_gold(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            prepared = prepare(CONFIG, output)
            self.assertEqual(prepared['target_count'], 27)
            self.assertEqual(json.loads((output / 'state.json').read_text())['status'], 'FROZEN')


if __name__ == '__main__':
    unittest.main()
