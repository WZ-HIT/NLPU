import tempfile
from pathlib import Path
import unittest

from experiment.trace_batch import make_scope, write_status
from test_trace.common import read_json, write_json


class TraceBatchTests(unittest.TestCase):
    def test_scope_whitelist_and_shared_base(self):
        rows = [{'pr_id': 2, 'base_sha': 'a'*40, 'gold_ranks': {'secret': 1}},
                {'pr_id': 1, 'base_sha': 'a'*40, 'test_diff': 'secret'}]
        result = make_scope(rows)
        self.assertEqual(result['pull_requests'], [{'pr_id': 1, 'base_sha': 'a'*40}, {'pr_id': 2, 'base_sha': 'a'*40}])
        self.assertNotIn('secret', str(result))
        rows[0]['gold_ranks'] = {'different': 2}
        self.assertEqual(result, make_scope(rows))
        with self.assertRaises(ValueError):
            make_scope([rows[0], rows[0]])

    def test_status_keeps_running_pending_partial_and_failed_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {'root': str(root), 'scope': {'pull_requests': [{}, {}, {}, {}]},
                    'max_test_workers': 16, 'jobs': [{'base_sha': str(i), 'pr_ids': [i]} for i in range(4)]}
            write_json(root/'terminals/0.json', {'status': 'SEALED_WITH_GAPS', 'bundle': str(root/'bundle'), 'manifest_sha256': 'abc'})
            write_json(root/'terminals/1.json', {'status': 'FAILED', 'error': 'explicit'})
            status = write_status(plan, {'2'})
            self.assertEqual(status['status_counts'], {'SEALED_WITH_GAPS': 1, 'FAILED': 1, 'RUNNING': 1, 'PENDING': 1})
            self.assertFalse(status['terminal'])
            self.assertFalse(status['all_bases_sealed'])
            artifacts = read_json(root/'dynamic-trace-artifacts.json')['artifacts']
            self.assertEqual(set(artifacts), {'0'})


if __name__ == '__main__':
    unittest.main()
