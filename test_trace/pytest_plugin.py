"""Load with ``pytest -p test_trace.pytest_plugin`` and TEST_TRACE_CONFIG.

Discovery preserves pytest execution identities. Collection accepts exactly one
selected Python item and activates only when its verified source body executes.
"""
from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

import pytest

from .collector import Collector
from .symbols import SymbolIndex


def _write(path: str, document: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + target.name, dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(document, stream, ensure_ascii=False, sort_keys=True)
            stream.write('\n')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def pytest_configure(config):
    path = os.environ.get('TEST_TRACE_CONFIG')
    if not path:
        return
    config.addinivalue_line('markers', 'flaky(reruns=0, reruns_delay=0): project retry marker; test_trace runs one attempt')
    settings = json.loads(Path(path).read_text(encoding='utf-8'))
    config._test_trace_settings = settings
    config._test_trace_index = SymbolIndex(settings['repository_root'], settings.get('production_roots', ()),
                                            settings.get('source_mappings', ()), settings.get('source_files'))
    config._test_trace_items = []
    config._test_trace_errors = []
    config._test_trace_reports = {}
    config._test_trace_collector = None


def _item_record(item, index):
    obj = getattr(item, 'obj', None)
    record = {'execution_id': item.nodeid, 'collector_type': type(item).__module__ + '.' + type(item).__qualname__}
    if obj is None:
        record.update(source_test_id=None, source_identity_status='unknown')
    else:
        record.update(index.resolve_callable(obj))
    try:
        record['collection_location'] = list(item.location)
    except (AttributeError, TypeError):
        record['collection_location'] = None
    if hasattr(item, 'callspec'):
        record['parameter_id'] = item.callspec.id
    record['original_name'] = getattr(item, 'originalname', item.name)
    return record


def pytest_collection_finish(session):
    config = session.config
    if not hasattr(config, '_test_trace_settings'):
        return
    index = config._test_trace_index
    config._test_trace_items = [_item_record(item, index) for item in session.items]
    index.register_test_ids(record['source_test_id'] for record in config._test_trace_items)
    if config._test_trace_settings['mode'] != 'collect':
        return
    if len(session.items) != 1:
        config._test_trace_errors.append({'code': 'EXACTLY_ONE_EXECUTION_REQUIRED', 'count': len(session.items)})
        session.shouldstop = 'test_trace requires exactly one selected execution item'
    elif (config._test_trace_settings.get('execution_id') is not None
          and session.items[0].nodeid != config._test_trace_settings['execution_id']):
        config._test_trace_errors.append({'code': 'EXECUTION_ID_MISMATCH', 'selected': session.items[0].nodeid,
                                          'expected': config._test_trace_settings['execution_id']})
        session.shouldstop = 'test_trace selected execution does not match its pinned identity'


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_call(item):
    config = item.config
    collector = None
    if (hasattr(config, '_test_trace_settings') and config._test_trace_settings['mode'] == 'collect'
            and len(config._test_trace_items) == 1):
        record = config._test_trace_items[0]
        settings = config._test_trace_settings
        collector = Collector(settings, config._test_trace_index)
        config._test_trace_collector = collector
        collector.execution_id = item.nodeid
        collector.source_test_id = record['source_test_id']
        # Third-party/custom Item implementations need their own verified
        # adapter; inheriting Function does not establish execution semantics.
        item_type = type(item)
        supported = ((item_type.__module__, item_type.__name__) in {
            ('_pytest.python', 'Function'), ('_pytest.unittest', 'TestCaseFunction'),
            ('_pytest.unittest', 'UnitTestFunction'), ('pytest_asyncio.plugin', 'Coroutine')})
        if not supported:
            collector.errors.append({'code': 'UNSUPPORTED_CUSTOM_ITEM', 'detail': type(item).__qualname__})
        elif record['source_identity_status'] != 'verified':
            collector.errors.append({'code': 'SOURCE_TEST_IDENTITY_UNKNOWN', 'detail': item.nodeid})
        else:
            underlying = inspect.unwrap(item.obj)
            underlying = getattr(underlying, '__func__', underlying)
            # Suppression covers dynamic fixture requests, including teardown
            # of a cached parametrized fixture before its replacement setup.
            from _pytest.fixtures import FixtureRequest, FixtureDef
            suppression = [FixtureRequest.getfixturevalue.__code__, FixtureDef.finish.__code__]
            suppression.extend(getattr(unittest.TestCase, name).__code__ for name in
                               ('_callSetUp', '_callTearDown', '_callCleanup', 'doCleanups', 'doClassCleanups')
                               if hasattr(getattr(unittest.TestCase, name), '__code__'))
            if hasattr(unittest, 'IsolatedAsyncioTestCase'):
                suppression.extend(getattr(unittest.IsolatedAsyncioTestCase, name).__code__ for name in
                                   ('_callSetUp', '_callTearDown', '_callCleanup'))
            instance = getattr(item, 'instance', None)
            if isinstance(instance, unittest.TestCase):
                for name in ('setUp', 'tearDown', 'asyncSetUp', 'asyncTearDown', '_callCleanup',
                             '_callSetUp', '_callTearDown', 'doCleanups', 'doClassCleanups'):
                    method = getattr(instance, name, None)
                    code = getattr(getattr(method, '__func__', method), '__code__', None)
                    if code is not None:
                        suppression.append(code)
            collector.add_suppression_codes(suppression)
            collector.arm(underlying.__code__, record['source_test_id'], item.nodeid)
    try:
        yield
    finally:
        if collector is not None:
            collector.disarm()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_fixture_setup(fixturedef, request):
    collector = getattr(request.config, '_test_trace_collector', None)
    token = collector.suppress() if collector is not None else None
    try:
        yield
    finally:
        if token is not None:
            collector.unsuppress(token)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    report = result.get_result()
    config = item.config
    if hasattr(config, '_test_trace_reports'):
        config._test_trace_reports[report.when] = {'outcome': report.outcome,
                                                  'duration': report.duration,
                                                  'wasxfail': getattr(report, 'wasxfail', None)}


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if not hasattr(config, '_test_trace_settings'):
        return
    settings = config._test_trace_settings
    errors = [*config._test_trace_errors, *config._test_trace_index.errors]
    if session.testsfailed and not config._test_trace_reports:
        errors.append({'code': 'COLLECTION_OR_SESSION_FAILURE', 'count': session.testsfailed})
    if settings['mode'] == 'discover':
        document = {'items': config._test_trace_items, 'errors': errors, 'exit_code': int(exitstatus),
                    'limitations': sorted(config._test_trace_index.limitations),
                    'excluded_sources': list(config._test_trace_index.excluded_sources.values()),
                    'snapshot_id': settings.get('snapshot_id'), 'base_sha': settings.get('base_sha')}
    else:
        collector = config._test_trace_collector
        if collector is None:
            collector = Collector(settings, config._test_trace_index)
            if len(config._test_trace_items) == 1:
                collector.execution_id = config._test_trace_items[0]['execution_id']
                collector.source_test_id = config._test_trace_items[0]['source_test_id']
        document = collector.document()
        reports = config._test_trace_reports
        passed = (int(exitstatus) == 0 and reports.get('call', {}).get('outcome') == 'passed'
                  and all(r['outcome'] == 'passed' and not r.get('wasxfail') for r in reports.values()))
        document['reports'] = reports
        document['exit_code'] = int(exitstatus)
        document['errors'].extend(error for error in errors if error not in document['errors'])
        document['outcome'] = ('passed' if passed else 'failed' if any(r['outcome'] == 'failed' for r in reports.values())
                               else 'skipped' if any(r['outcome'] == 'skipped' for r in reports.values()) else 'error')
        boundary = document['body_boundary_status'] == 'verified'
        document['source_identity_status'] = 'verified' if document['source_test_id'] else 'unknown'
        document['evidence_status'] = ('valid' if passed and boundary and not document['errors']
                                       else 'diagnostic' if boundary else 'unsupported')
    _write(settings['output_file'], document)
