import json
from pathlib import Path
import tempfile
import unittest

from batch.core import BatchError, sha256_file
from batch.test_intention import bundles, verify_bundle


class IntentionInputTests(unittest.TestCase):
    def test_bundle_is_pinned_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            package=root/'bundle'
            package.mkdir()
            for name in ('README.md','index.json','relations.json'):
                (package/name).write_text('{}')
            manifest={'base_sha':'a'*40,'files':{p.name:sha256_file(p) for p in package.iterdir()}}
            (package/'manifest.json').write_text(json.dumps(manifest))
            config={'test_intention':{'entrypoint':'test-intentions/README.md','artifacts':{
                'a'*40:{'path':'bundle/manifest.json','sha256':sha256_file(package/'manifest.json')}}}}
            self.assertEqual(bundles(config,root,{'a'*40}),{'a'*40:package})
            outside = root / 'outside'
            outside.mkdir()
            (outside / 'sentinel').write_text('private')
            (package / 'unlisted-link').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(BatchError):
                verify_bundle(package/'manifest.json','a'*40)
            (package / 'unlisted-link').unlink()
            (package/'index.json').write_text('changed')
            with self.assertRaises(BatchError):
                verify_bundle(package/'manifest.json','a'*40)

    def test_old_configuration_unchanged_and_base_mismatch_rejected(self):
        self.assertEqual(bundles({},Path('/unused'),{'a'*40}),{})
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'manifest.json'
            p.write_text(json.dumps({'base_sha':'a'*40,'files':{}}))
            with self.assertRaises(BatchError):
                verify_bundle(p,'b'*40)


if __name__=='__main__':
    unittest.main()
