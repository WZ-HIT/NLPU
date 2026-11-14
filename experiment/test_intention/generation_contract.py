"""Same whole-packet intention contract, with precise, stable error locations."""
import json

from .generation import INSTRUCTIONS, validate as legacy_validate
from .static import digest

VERSION = 'source-evidence-intention-2'
INSTRUCTIONS_V2 = INSTRUCTIONS + '''
Each test has an allowed_evidence_ids array. For THAT test, every scenario must
include its own exact id and use only ids from THAT array, not a peer's array.
Copy evidence IDs exactly; do not turn code symbols, paths, lines or descriptions
into evidence IDs. Never repair references by inventing evidence. Retain unknowns.
'''
OPTIONS = dict(model='deepseek-flash', effort='high', max_output_tokens=16384,
               prompt_version=VERSION, instructions_sha256=digest(INSTRUCTIONS_V2))


class ContractError(ValueError):
    def __init__(self, code, path, *, test_id=None, detail=None):
        self.record = dict(code=code, path=path, test_id=test_id, detail=detail)
        super().__init__(json.dumps(self.record, ensure_ascii=False))


def request_packet(packet):
    return {**packet, 'tests': [{**test, 'allowed_evidence_ids': [test['id'], *test['contexts']]}
                              for test in packet['tests']]}


def validate(value, packet):
    def fail(code, path, identity=None, detail=None):
        raise ContractError(code, path, test_id=identity, detail=detail)

    def strings(value, path, identity):
        if not isinstance(value, list):
            fail('ARRAY_REQUIRED', path, identity)
        for i, item in enumerate(value):
            if not isinstance(item, str):
                fail('STRING_REQUIRED', f'{path}/{i}', identity)

    if not isinstance(value, dict) or set(value) != {'tests'} or not isinstance(value['tests'], list):
        fail('ROOT_TESTS_ARRAY_REQUIRED', '/')
    originals = {t['id']: t for t in packet['tests']}
    seen = set()
    peer_contexts = {c for test in packet['tests'] for c in test['contexts']}
    fields = {'id','summary','operations','inputs','environment_mock','scenarios','uncertainties'}
    for i, test in enumerate(value['tests']):
        path = f'/tests/{i}'
        if not isinstance(test, dict) or set(test) != fields:
            fail('TEST_FIELDS_INVALID', path)
        identity = test['id']
        if not isinstance(identity, str) or identity not in originals:
            fail('TEST_ID_UNKNOWN', path+'/id')
        if identity in seen:
            fail('TEST_ID_DUPLICATED', path+'/id', identity)
        seen.add(identity)
        if not isinstance(test['summary'], str):
            fail('STRING_REQUIRED', path+'/summary', identity)
        for field in ('operations','inputs','environment_mock','uncertainties'):
            strings(test[field], path+'/'+field, identity)
        if not isinstance(test['scenarios'], list) or not test['scenarios']:
            fail('NONEMPTY_SCENARIOS_REQUIRED', path+'/scenarios', identity)
        allowed = {identity, *originals[identity]['contexts']}
        for j, scenario in enumerate(test['scenarios']):
            location = f'{path}/scenarios/{j}'
            if not isinstance(scenario, dict) or set(scenario) != {'conditions','actions','expected','evidence'}:
                fail('SCENARIO_FIELDS_INVALID', location, identity)
            for field in scenario:
                strings(scenario[field], location+'/'+field, identity)
            if identity not in scenario['evidence']:
                fail('EVIDENCE_OWN_TEST_MISSING', location+'/evidence', identity)
            for k, reference in enumerate(scenario['evidence']):
                if reference not in allowed:
                    code = 'EVIDENCE_PEER_CONTEXT' if reference in peer_contexts or reference in originals else 'EVIDENCE_NOT_SUPPLIED'
                    fail(code, f'{location}/evidence/{k}', identity, {'reference': reference})
    if seen != originals.keys():
        fail('TEST_IDS_MISSING', '/tests', detail={'missing': sorted(originals.keys()-seen)})
    # Retain compatibility with the established contract, not a permissive subset.
    return legacy_validate(value, packet)
