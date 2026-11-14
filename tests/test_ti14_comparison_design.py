import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from collections import Counter

from experiment.test_intention.comparison_design import design
from experiment.test_intention.static import write


class ComparisonDesignTests(unittest.TestCase):
    def test_paired_schedule_scope_balance_and_execution_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prs = list(range(100, 130))
            methods = ['openspec', 'speckit', 'cc-sdd']
            write(root/'original/scope.json', {'targets': [dict(task_id=f'scrapy__scrapy__pr{p}',
                 method=m, base_sha='a'*40, task_manifest={'path':'unused', 'sha256':'unused'}) for p in prs for m in methods]})
            write(root/'split.json', dict(development_prs=prs, held_out_prs=[999]))
            write(root/'audit/summary.json', dict(status='PASS', base_count=1, test_records=5,
                    status_counts={'GENERATED':4,'STATIC_FALLBACK':1},packet_reason_counts={}))
            with patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')):
                config = design(root/'original', root/'split.json', root/'audit', root/'design')
            schedule = json.loads((root/'design/schedule.json').read_text())
            self.assertFalse(config['execution_allowed'])
            self.assertEqual(len(schedule), 270)
            self.assertEqual(len({(r['pr'],r['method'],r['group'],r['repeat']) for r in schedule}),270)
            self.assertEqual(sum(r['pilot'] for r in schedule),27)
            self.assertEqual(Counter(r['group'] for r in schedule),{'A':90,'B':90,'C':90})
            self.assertEqual(set(Counter((r['position'],r['group']) for r in schedule).values()),{30})
            self.assertFalse(any(r['pr']==999 for r in schedule))
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                design(root/'original', root/'split.json', root/'audit', root/'design')

    def test_failed_coverage_blocks_design(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root/'audit/summary.json', {'status':'FAIL'})
            with self.assertRaisesRegex(ValueError, 'TI-13'):
                design(root/'unused',root/'unused',root/'audit',root/'design')
            self.assertFalse((root/'design').exists())
