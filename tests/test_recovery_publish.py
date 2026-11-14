import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from experiment.test_intention import compact, generation, p1_bundle, p2_bundle
from experiment.test_intention.coverage_audit import OPTIONS as OLD_OPTIONS
from experiment.test_intention.static import build, batches, digest, write
from experiment.test_intention.recovery import make_plan, sha, Recovery
from experiment.test_intention.recovery_publish import publish, sample, reviewed


def semantic(packet):
    return {'tests':[dict(id=t['id'],summary='Checks equality.',operations=['compare'],inputs=[],environment_mock=[],
          uncertainties=[],scenarios=[dict(conditions=[],actions=['compare'],expected=['equal'],evidence=[t['id']])])
          for t in packet['tests']]}


class PublicationTests(unittest.TestCase):
    def test_recovered_semantics_quality_gate_reader_and_static_preservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base='a'*40
            repo=root/'repo';(repo/'tests').mkdir(parents=True)
            (repo/'tests/test_sample.py').write_text('def test_old():\n    assert 1 == 1\n\ndef test_new():\n    assert 2 == 2\n')
            original=root/'original';audit=root/'audit'
            document=build(repo,base);packets=list(batches(document,batch_size=1))
            write(original/'static'/f'{base}.json',document);write(original/'scope.json',{'base_shas':[base]})
            class Keyer:
                def key(self,source):return digest({'packet':source,'options':OLD_OPTIONS})
            keyer=Keyer();metadata=[];coverage=[]
            for packet in packets:
                generated=packet['tests'][0]['id'].endswith('test_old')
                key=keyer.key(packet);path=original/'generation-cache'/f'{key}.json'
                write(path,dict(packet=packet,options=OLD_OPTIONS,status='GENERATED' if generated else 'STATIC_FALLBACK',
                    result=semantic(packet) if generated else None,attempts=[],usage=[],input_sha256=key,error=None))
                metadata.append(dict(cache_path=str(path),cache_sha256=sha(path),cache_key=key,status='GENERATED' if generated else 'STATIC_FALLBACK',
                   base_shas=[base],versioned_test_records=1,reason='GENERATED' if generated else 'BUDGET_REJECTED_LIMIT_UNKNOWN',request_journal_ids=[]))
                coverage.append(dict(base_sha=base,id=packet['tests'][0]['id'],cache_key=key))
            write(audit/'packets.json',metadata);write(audit/'requests.json',[]);write(audit/'coverage.json',coverage)
            write(audit/'summary.json',dict(status='PASS',accounting={}))
            write(audit/'coverage-groups.json',[dict(group=base,group_type='base')])
            generation.render(document,packets,original/'generation-cache',root/'raw',keyer)
            compact.export_base(root/'raw',root/'v2');p1_bundle.export(root/'v2',root/'v3')
            p2_bundle.export(root/'v3',repo,root/'current'/base)
            write(audit/'sources.json',{'sha256':{str((root/'current'/base/name).resolve()):sha(root/'current'/base/name)
                                                for name in ('manifest.json','.evidence.sqlite3')}})
            original_hash=sha(root/'current'/base/'.evidence.sqlite3')
            plan=make_plan(audit,original,root/'plan')
            def fake(payload,secret):
                source=json.loads(payload['input'])
                return dict(id='fake',model='deepseek-flash',status='completed',usage={'input_tokens':100,'output_tokens':100},
                    output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(semantic(source)))])])
            with patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
                Recovery(root/'execution',plan,plan_hash=sha(root/'plan/plan.json'),max_new_cny=10,transport=fake).run()
                count=sample(root/'plan',root/'current',root/'execution',root/'quality')
                self.assertEqual(count,2)
                with self.assertRaisesRegex(ValueError,'incomplete'):reviewed(root/'quality')
                review=json.loads((root/'quality/review.json').read_text())
                for record in review['records']:
                    record.update(decision='ACCEPT',notes='Fixture review of the equality assertion.',
                                  source_anchors=[record['location']])
                write(root/'quality/review.json',review)
                summary=publish(root/'plan',root/'current',root/'execution',root/'quality',root/'published')
            self.assertEqual(summary['status'],'COMPLETE_COVERAGE');self.assertEqual(summary['generated'],2)
            bundle=root/'published/representations'/base
            self.assertEqual(original_hash,sha(root/'current'/base/'.evidence.sqlite3'))
            self.assertEqual(sha(bundle/'.maintenance.sqlite3'),sha(root/'current'/base/'.maintenance.sqlite3'))
            with sqlite3.connect(bundle/'.evidence.sqlite3') as db:
                cards=[json.loads(c) for c, in db.execute('SELECT card FROM tests')]
                self.assertTrue(all(c['status']=='GENERATED' for c in cards))
            import subprocess
            query=subprocess.run(['python3','-B',str(bundle/'read.py'),'search','--query','Checks equality.'],capture_output=True)
            self.assertEqual(query.returncode,0,query.stderr)
            self.assertLessEqual(len(query.stdout),6000)
            page=json.loads(query.stdout);self.assertEqual(len(page['items']),2)
            for relative,checksum in json.loads((bundle/'manifest.json').read_text())['files'].items():
                self.assertEqual(sha(bundle/relative),checksum)
            for record in review['records']:
                if record['origin']=='new':record['decision']='QUARANTINE_PACKET'
            write(root/'quality/review.json',review)
            quarantined=publish(root/'plan',root/'current',root/'execution',root/'quality',root/'quarantined')
            self.assertEqual(quarantined['generated'],1)
            self.assertEqual(quarantined['fallback'],1)
            self.assertEqual(quarantined['status'],'PARTIAL_COVERAGE')
            with sqlite3.connect(root/'execution/ledger.sqlite3') as db:
                key,detail=db.execute('SELECT key,detail FROM packets').fetchone()
                changed=dict(json.loads(detail),review_revision='changed after quality sample')
                db.execute('UPDATE packets SET detail=? WHERE key=?',(json.dumps(changed),key))
            with self.assertRaisesRegex(ValueError,'different generation state'):
                publish(root/'plan',root/'current',root/'execution',root/'quality',root/'stale')
