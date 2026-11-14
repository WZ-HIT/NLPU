import json
from pathlib import Path
import tempfile
import unittest

from experiment.test_intention.codex_recovery import OPTIONS, CodexRecovery, command, quota_allows
from experiment.test_intention.static import digest


class CodexRecoveryTests(unittest.TestCase):
    def test_quota_guard_and_no_paid_fallback_in_command(self):
        self.assertFalse(quota_allows({})[0])
        self.assertFalse(quota_allows({'rateLimits':{'primary':{'usedPercent':95}}})[0])
        self.assertFalse(quota_allows({'rateLimits':{'secondary':{'usedPercent':100}}})[0])
        self.assertTrue(quota_allows({'rateLimits':{'primary':{'usedPercent':27}}})[0])
        args=command(Path('/plan'),Path('/work'),Path('/output'))
        self.assertIn('--ignore-user-config',args)
        self.assertIn('forced_login_method="chatgpt"',args)
        self.assertIn('model_provider="openai"',args)
        self.assertIn('project_doc_max_bytes=0',args)
        self.assertIn('shell_tool',args)
        self.assertIn('multi_agent',args)
        self.assertNotIn('--oss',args)

    def test_subscription_usage_recorded_and_exhaustion_preserves_pending(self):
        source=dict(tests=[dict(id='tests/a.py::test_a',source='def test_a(): assert True',contexts=[],uncertainty=[])],contexts=[])
        semantic=dict(id='tests/a.py::test_a',summary='Asserts truth.',operations=['assert'],inputs=[],environment_mock=[],
            uncertainties=[],scenarios=[dict(conditions=[],actions=['assert'],expected=['true'],evidence=['tests/a.py::test_a'])])
        key=digest({'packet':source,'options':OPTIONS})
        plan=dict(backend='codex-subscription',options=OPTIONS,workers=1,request_upper_bound=2,historical_accounting={},
            rows=[dict(new_key=key,old_key='old',packet=source,packet_sha256=digest(source),allowed_new_requests=2)])
        class FakeTransport:
            stop_reason=None
            def __call__(self,*args):
                return dict(id='fake',model=OPTIONS['model'],status='completed',usage={'input_tokens':100,'output_tokens':100},
                   output=[dict(type='message',content=[dict(type='output_text',text=json.dumps({'tests':[semantic]}))])])
        class Rates:
            used=100
            def limits(self):return {'rateLimits':{'primary':{'usedPercent':self.used}}}
        with tempfile.TemporaryDirectory() as temporary:
            runner=CodexRecovery(Path(temporary),plan,plan_hash='same',max_new_cny=0,transport=FakeTransport())
            rates=Rates()
            status=runner.run_subscription(rates)
            self.assertEqual(status['new_request_count'],0)
            self.assertEqual(status['states'],{'PENDING':1})
            rates.used=0
            status=runner.run_subscription(rates)
            self.assertEqual(status['states'],{'GENERATED':1})
            self.assertEqual(status['new_accounted_or_reserved_cny'],0)
            self.assertEqual(status['billing_mode'],'chatgpt-subscription')
            output=json.loads((Path(temporary)/'results'/f'{key}.json').read_text())
            self.assertEqual(output['options'],OPTIONS)
