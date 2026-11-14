import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from experiment.test_intention.coverage_audit import OPTIONS, audit, reason
from experiment.test_intention.static import batches, build, digest, write


class CoverageAuditTests(unittest.TestCase):
    def test_terminal_reasons_preserve_uncertainty(self):
        self.assertEqual(reason(None, []), 'NOT_SCHEDULED')
        self.assertEqual(reason(None, [{}]), 'REQUEST_WITHOUT_FINAL_CACHE')
        for error, expected in [
            ('Configured generation request or cost ceiling reached', 'BUDGET_REJECTED_LIMIT_UNKNOWN'),
            ('Scenario evidence must reference own test and supplied context', 'EVIDENCE_REFERENCE_ERROR'),
            ('Provider response did not complete: incomplete', 'OUTPUT_INCOMPLETE'),
            ('RuntimeError: Provider HTTP status 429', 'PROVIDER_OR_NETWORK_ERROR'),
            ('Expected a JSON object containing only a tests array', 'FORMAT_ERROR'),
            ('Single source packet exceeds 64000 character ceiling', 'OVERSIZE_INPUT'),
            ('An unrecognized historical error', 'OTHER_UNKNOWN'),
        ]:
            self.assertEqual(reason({'status': 'STATIC_FALLBACK', 'error': error}, []), expected)

    def fixture(self, root):
        original, current, bases = root/'original', root/'current', root/'bases'
        base = 'a'*40
        repository = bases/base/'repository'
        (repository/'tests').mkdir(parents=True)
        (repository/'tests/test_one.py').write_text('def test_one():\n    assert 1 == 1\n')
        document = build(repository, base)
        packet = list(batches(document))[0]
        key = digest({'packet': packet, 'options': OPTIONS})
        semantic = dict(id=document['tests'][0]['id'], summary='Checks equality.', operations=['compare'],
                        inputs=[], environment_mock=[], scenarios=[dict(conditions=[], actions=['compare'],
                        expected=['1 equals 1'], evidence=[document['tests'][0]['id']])], uncertainties=[])
        write(original/'scope.json', {'base_shas': [base]})
        write(original/'generation-plan.json', {'raw_test_records': 1, 'unique_batches': 1})
        write(original/'generation-summary.json', dict(calls_in_request_journal=2, generated_batches=1,
                                                       fallback_batches=0, cost_ceiling_cny=200))
        write(original/'static'/f'{base}.json', document)
        write(original/'packets'/f'{base}.json', [packet])
        write(original/'generation-cache'/f'{key}.json', dict(input_sha256=key, options=OPTIONS, packet=packet,
                    status='GENERATED', result={'tests': [semantic]}, attempts=[], usage=[], error=None))
        # An unknown-cost request must never become zero actual spend.
        write(original/'generation-cache/requests/request1.json', dict(request_id='request1', input_sha256=key,
                    reservation_cny=.2, status='REQUEST_FAILED_COST_UNKNOWN', usage=None))
        write(original/'generation-cache/requests/migrated-probe.json', dict(input_sha256=key,
                    reservation_cny=.01, accounted_cost_cny=.001, status='completed',
                    usage={'input_tokens': 100, 'output_tokens': 100}, note='migrated usage, no new request'))
        manifest = dict(source_files=document['source_files'], base_sha=base, generated_count=1, fallback_count=0)
        write(original/'representations'/base/'manifest.json', manifest)
        bundle = current/base
        bundle.mkdir(parents=True)
        test = document['tests'][0]
        with sqlite3.connect(bundle/'.evidence.sqlite3') as db:
            db.execute('CREATE TABLE tests(id TEXT,card TEXT,intention TEXT,facts TEXT,location TEXT)')
            db.execute('INSERT INTO tests VALUES(?,?,?,?,?)', (test['id'], json.dumps({'status': 'GENERATED'}),
                       json.dumps(semantic), json.dumps(test['static']), json.dumps(test['source'])))
        import hashlib
        manifest['files'] = {'.evidence.sqlite3': hashlib.sha256((bundle/'.evidence.sqlite3').read_bytes()).hexdigest()}
        write(bundle/'manifest.json', manifest)
        return original, current, bases

    def test_full_join_and_no_network_or_generator(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = self.fixture(root)
            before = {p: p.read_bytes() for path in args for p in path.rglob('*') if p.is_file()}
            with patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')), \
                 patch('experiment.test_intention.generation.Generator.__init__', side_effect=AssertionError('Generator forbidden')):
                summary = audit(*args, root/'audit')
            self.assertEqual(summary['status'], 'PASS', summary['violations'])
            self.assertEqual(summary['accounting']['missing_usage_requests'], 1)
            self.assertEqual(summary['legacy_request_id_missing_count'], 1)
            self.assertEqual(summary['accounting']['unknown_spend_reservation_cny'], .2)
            self.assertIsNone(summary['accounting']['actual_provider_invoice_cost_cny'])
            self.assertEqual(summary['generated_empty_fields']['inputs'], 1)
            self.assertEqual(summary['semantic_quality_reviews_performed'], 0)
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            self.assertTrue((root/'audit/completion.json').exists())
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                audit(*args, root/'audit')

    def test_modified_visible_semantics_fails_even_when_hash_resealed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original, current, bases = self.fixture(root)
            bundle = current/('a'*40)
            with sqlite3.connect(bundle/'.evidence.sqlite3') as db:
                semantic = json.loads(db.execute('SELECT intention FROM tests').fetchone()[0])
                semantic['summary'] = 'Changed after publication'
                db.execute('UPDATE tests SET intention=?', (json.dumps(semantic),))
            import hashlib
            manifest = json.loads((bundle/'manifest.json').read_text())
            manifest['files']['.evidence.sqlite3'] = hashlib.sha256((bundle/'.evidence.sqlite3').read_bytes()).hexdigest()
            write(bundle/'manifest.json', manifest)
            summary = audit(original, current, bases, root/'audit')
            self.assertEqual(summary['status'], 'FAIL')
            self.assertIn('CURRENT_SEMANTIC_MISMATCH', [v['code'] for v in summary['violations']])

    def test_cross_base_reuse_does_not_duplicate_request_count(self):
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original, current, bases = self.fixture(root)
            first, second = 'a'*40, 'b'*40
            shutil.copytree(bases/first, bases/second)
            shutil.copytree(current/first, current/second)
            for parent in (original/'static',):
                document = json.loads((parent/f'{first}.json').read_text())
                document['base_sha'] = second
                write(parent/f'{second}.json', document)
            shutil.copyfile(original/'packets'/f'{first}.json',original/'packets'/f'{second}.json')
            for parent in (original/'representations',current):
                manifest = json.loads((parent/first/'manifest.json').read_text())
                manifest['base_sha'] = second
                write(parent/second/'manifest.json',manifest)
            write(original/'scope.json', {'base_shas':[first,second]})
            write(original/'generation-plan.json', {'raw_test_records':2,'unique_batches':1})
            summary = audit(original,current,bases,root/'audit')
            self.assertEqual(summary['status'],'PASS',summary['violations'])
            self.assertEqual(summary['test_records'],2)
            self.assertEqual(summary['base_packet_occurrences'],2)
            self.assertEqual(summary['unique_input_packets'],1)
            self.assertEqual(summary['scope_request_journal_count'],2)


if __name__ == '__main__':
    unittest.main()
