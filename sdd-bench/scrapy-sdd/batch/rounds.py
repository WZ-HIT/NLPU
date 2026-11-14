"""Pinned, isolated Detect rounds over existing approved source batches.

The round label chooses a fresh task tree and ledger. It never changes source
batch identities or reuses an Agent workspace from another round.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .core import BatchError, canonical_sha256, sha256_file, validate_plan_inputs, write_json
from .prepare import ROOT, _image_record, _pinned, _target, _validate
from .orchestrator import validate_batch_config
from .scaffold import scaffold_tasks
from .gold_audit import run_audit
from .compose_preflight import run_preflight

BENCH = ROOT / 'sdd-bench/scrapy-sdd'


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise BatchError('ROUND_DOCUMENT_INVALID', 'Expected a JSON object', path=str(path))
    return value


def _ref(path: Path, root: Path) -> dict[str, str]:
    if path.is_symlink():
        raise BatchError('ROUND_EVIDENCE_MISSING', 'Round evidence file is a symlink', path=str(path))
    path = path.resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise BatchError('ROUND_EVIDENCE_MISSING', 'Round evidence file is missing', path=str(path))
    return {'path': path.relative_to(root).as_posix(), 'sha256': sha256_file(path)}


def compile_round(config_path: Path, round_label: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Read only: resolve the selected 30 (or fewer) PRs to pinned sources."""
    root = root.resolve(); bench = root / 'sdd-bench/scrapy-sdd'
    if config_path.is_symlink():
        raise BatchError('ROUND_CONFIG_INVALID', 'Config cannot be a symlink')
    config_path = config_path.resolve()
    if not config_path.is_file() or not config_path.is_relative_to(root):
        raise BatchError('ROUND_CONFIG_INVALID', 'Config must be a repository file')
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,127}', round_label):
        raise BatchError('ROUND_LABEL_INVALID', 'Round label must be a safe identifier')
    config = _read(config_path)
    if len(config.get('prs', [])) != len(set(map(str, config.get('prs', [])))):
        raise BatchError('PREPARE_DUPLICATE_PR', 'PR appears more than once')
    _validate(config, 'experiment-config-v2.schema.json')
    selected = {f"scrapy__scrapy__pr{pr}": pr for pr in config['prs']}
    owners: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    source_records = []
    for source_ref in config['sources']:
        source_path = _pinned(root, source_ref)
        source, _ = validate_batch_config(source_path, bench, root)
        approved = source['approved_plan']
        plan = _read(_pinned(root, {'path': approved['path'], 'sha256': approved['sha256']}))
        if not validate_plan_inputs(plan, root)['valid']:
            raise BatchError('ROUND_INPUT_STALE', 'Approved plan inputs are stale', plan=approved['plan_id'])
        report = _pinned(root, {'path': approved['provision_report_path'], 'sha256': approved['provision_report_sha256']})
        planned = {entry['task_id']: entry for entry in plan['tasks']}
        source_records.append({'source': source_ref, 'plan': plan, 'plan_path': root / approved['path'],
                               'report_path': report, 'approved_id': approved['plan_id']})
        for task in source['tasks']:
            task_id = task['task_id']
            if task_id not in selected:
                continue
            if task_id in owners:
                raise BatchError('ROUND_PR_AMBIGUOUS', 'Selected PR appears in multiple pinned batches', task_id=task_id)
            if task_id not in planned:
                raise BatchError('ROUND_PLAN_MISMATCH', 'Selected task is absent from its approved plan', task_id=task_id)
            owners[task_id] = (task, planned[task_id], source_ref)
    missing = set(selected) - set(owners)
    if missing:
        raise BatchError('ROUND_PR_NOT_IN_SOURCES', 'Selected PR is absent from pinned batches', tasks=sorted(missing))
    origin_ref = _ref(config_path, root)
    # The config is frozen by content, so later edits to the user's one working
    # config cannot make an older round unreadable. Compilation itself is read-only.
    config_ref = {'path': f'sdd-bench/scrapy-sdd/batch/round-configs/{origin_ref["sha256"]}.json',
                  'sha256': origin_ref['sha256']}
    prepared_id = 'round-' + canonical_sha256({'config': config_ref, 'round_label': round_label})[:24]
    images = [_image_record(root, base) for base in sorted({p['baseline']['base_sha'] for _, p, _ in owners.values()})]
    from .test_intention import bundles
    test_intentions = bundles(config, root, {image['base_sha'] for image in images})
    from .dynamic_trace import bundles as trace_bundles
    dynamic_traces = trace_bundles(config, root, {image['base_sha'] for image in images})
    targets = []
    for pr in config['prs']:
        task_id = f'scrapy__scrapy__pr{pr}'
        task, planned, _ = owners[task_id]
        original = _pinned(root, task['task_manifest'])
        public = _read(original)
        base = planned['baseline']['base_sha']
        if public.get('task_id') != task_id or public.get('baseline', {}).get('base_sha') != base:
            raise BatchError('ROUND_TASK_MISMATCH', 'Pinned task differs from plan', task_id=task_id)
        methods = {item['method']: item for item in task['methods']}
        for method in config['methods']:
            if method not in methods:
                raise BatchError('ROUND_METHOD_MISSING', 'Method absent from pinned source', task_id=task_id, method=method)
            run_id = methods[method]['detect']['run_id']
            targets.append(_target(task_id, method, 'detect', None, run_id, base, task['task_manifest'], None))
    keys = [(t['task_id'], t['method'], t['stage'], t['mode'], t['run_id']) for t in targets]
    if len(keys) != len(set(keys)):
        raise BatchError('ROUND_TARGET_DUPLICATE', 'Expanded target identity is duplicated')
    return {'config': config, 'config_ref': config_ref, 'origin_ref': origin_ref, 'prepared_id': prepared_id,
            'round_label': round_label, 'sources': config['sources'], 'source_records': source_records,
            'owners': owners, 'images': images, 'targets': targets, 'test_intentions': test_intentions,
            'dynamic_traces': dynamic_traces}


def round_path(config_path: Path, round_label: str, *, root: Path = ROOT) -> Path:
    compiled = compile_round(config_path, round_label, root=root)
    return root / 'sdd-bench/scrapy-sdd/batch/runs' / compiled['prepared_id'] / 'prepared-round.json'


def _verify_task(task_root: Path, source_task: dict[str, Any], root: Path) -> list[dict[str, str]]:
    evidence = []
    if (task_root / 'test-intention.json').exists():
        evidence.append(_ref(task_root / 'test-intention.json', root))
    if (task_root / 'dynamic-trace.json').exists():
        evidence.append(_ref(task_root / 'dynamic-trace.json', root))
    expected = source_task['task_manifest']['sha256']
    task_path = task_root / 'task.json'
    if not task_path.is_file() or sha256_file(task_path) != expected:
        raise BatchError('ROUND_SCAFFOLD_CONFLICT', 'Fresh task differs from pinned task identity', task_id=task_root.name)
    for relative in ('task.json', 'experiment-inputs/task.md', 'stage-policy.json',
                     'initial-workspaces.json', 'isolation-audit.json', 'preflight-summary.json',
                     'compose-deployment-lock.json'):
        evidence.append(_ref(task_root / relative, root))
    audit = _read(task_root / 'isolation-audit.json')
    if audit.get('status') != 'PASS' or audit.get('gold_values_recorded') is not False:
        raise BatchError('ROUND_GOLD_AUDIT_INVALID', 'Gold isolation failed', task_id=task_root.name)
    summary = _read(task_root / 'preflight-summary.json')
    if (summary.get('task_id') != task_root.name or summary.get('runtime_preflight_status') != 'READY'
            or summary.get('model_request_sent') is not False
            or summary.get('compose_deployment_lock_sha256') != sha256_file(task_root / 'compose-deployment-lock.json')):
        raise BatchError('ROUND_PREFLIGHT_INVALID', 'Runtime preflight is not ready', task_id=task_root.name)
    reports = {(r['method'], r['stage']): r for r in summary.get('reports', [])}
    for method in ('openspec', 'speckit', 'cc-sdd'):
        evidence.append(_ref(task_root / 'initialization' / method / 'manifest.json', root))
        report = _read(task_root / 'runs' / method / 'detect/audit/gold-check-report.json')
        if report.get('status') != 'PASS' or report.get('agent_call_permitted') is not True:
            raise BatchError('ROUND_GOLD_AUDIT_INVALID', 'Detect gold audit did not pass', task_id=task_root.name, method=method)
        evidence.append(_ref(task_root / 'runs' / method / 'detect/audit/gold-check-report.json', root))
        runtime = reports.get((method, 'detect'))
        if runtime is None or runtime.get('runtime_boundary_pass') is not True:
            raise BatchError('ROUND_PREFLIGHT_INVALID', 'Detect runtime boundary failed', task_id=task_root.name, method=method)
        _pinned(root, {'path': runtime['report'], 'sha256': runtime['report_sha256']})
        evidence.append({'path': runtime['report'], 'sha256': runtime['report_sha256']})
    return evidence




def _freeze_config_snapshot(config_path: Path, config_ref: dict[str, str], root: Path) -> Path:
    """Publish the exact working config bytes once, under their content hash."""
    snapshot = root / config_ref['path']
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.exists():
        _pinned(root, config_ref)
    else:
        descriptor, temporary_name = tempfile.mkstemp(prefix='.round-config-', dir=snapshot.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(config_path.resolve().read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            if sha256_file(temporary) != config_ref['sha256']:
                raise BatchError('ROUND_CONFIG_CHANGED', 'Config changed during preparation')
            try:
                os.link(temporary, snapshot)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
        _pinned(root, config_ref)
    return snapshot


def prepare_round(config_path: Path, round_label: str, *, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve(); bench = root / 'sdd-bench/scrapy-sdd'
    compiled = compile_round(config_path, round_label, root=root)
    _freeze_config_snapshot(config_path, compiled['config_ref'], root)
    round_root = bench / 'batch/runs' / compiled['prepared_id']
    frozen_path = round_root / 'prepared-round.json'
    if frozen_path.exists():
        frozen = load_round(frozen_path, root=root, expected=compiled)
        (round_root / 'ledger.jsonl').touch(exist_ok=True)
        return frozen
    if (round_root / 'ledger.jsonl').exists():
        raise BatchError('ROUND_UNFROZEN_LEDGER', 'Round has a ledger but no prepared manifest')
    round_root.mkdir(parents=True, exist_ok=True)
    selected_by_source: dict[str, set[str]] = defaultdict(set)
    for task_id, (_, _, ref) in compiled['owners'].items():
        selected_by_source[ref['path']].add(task_id)
    for record in compiled['source_records']:
        chosen = selected_by_source[record['source']['path']]
        if chosen:
            scaffold_tasks(plan_path=record['plan_path'], provision_report_path=record['report_path'],
                           approved_plan_id=record['approved_id'], bench_root=bench, repository_root=root,
                           tasks_root=round_root / 'tasks', task_ids=chosen,
                           **({'test_intentions': compiled['test_intentions']}
                              if compiled.get('test_intentions') else {}),
                           **({'dynamic_traces': compiled['dynamic_traces']}
                              if compiled.get('dynamic_traces') else {}))
    evidence = [compiled['config_ref'], *compiled['sources']]
    if compiled['config'].get('test_intention'):
        evidence.extend(compiled['config']['test_intention']['artifacts'].values())
    if compiled['config'].get('dynamic_trace'):
        evidence.extend(compiled['config']['dynamic_trace']['artifacts'].values())
    for record in compiled['source_records']:
        evidence.extend((_ref(record['plan_path'], root), _ref(record['report_path'], root)))
    for image in compiled['images']:
        evidence.extend((image['baseline_lock'], image['deployment_lock']))
    for task_id, (source_task, _, source_ref) in compiled['owners'].items():
        task_root = round_root / 'tasks' / task_id
        if sha256_file(task_root / 'task.json') != source_task['task_manifest']['sha256']:
            raise BatchError('ROUND_SCAFFOLD_CONFLICT', 'Fresh task differs from pinned source before gold audit', task_id=task_id)
        if not (task_root / 'isolation-audit.json').exists():
            record = next(r for r in compiled['source_records'] if r['source'] == source_ref)
            run_audit(task=task_root, plan_path=record['plan_path'], bench=bench, repository_root=root)
        if not (task_root / 'preflight-summary.json').exists():
            run_preflight(task=task_root, bench=bench, repository_root=root,
                          run_id='preflight-' + compiled['prepared_id'][6:])
        evidence.extend(_verify_task(task_root, source_task, root))
    testcase_indexes = {}
    if compiled['config']['evaluation'].get('localization_protocol') == 'testcase-v1':
        from .testcase_identity import inventory, verified_baseline
        for image in compiled['images']:
            base = image['base_sha']
            repository, _ = verified_baseline(bench, base)
            index = inventory(repository, base)
            if index['errors']:
                raise BatchError('TESTCASE_INDEX_INCOMPLETE', 'Baseline testcase index has unreadable sources', base_sha=base)
            index_path = round_root / 'testcase-indexes' / (base + '.json')
            if index_path.exists():
                if _read(index_path) != index:
                    raise BatchError('TESTCASE_INDEX_CONFLICT', 'Existing validation index differs from baseline')
            else:
                write_json(index_path, index, refuse_overwrite=True)
            testcase_indexes[base] = _ref(index_path, root)
            evidence.append(testcase_indexes[base])
    staged = []
    for target in compiled['targets']:
        item = dict(target)
        task_path = round_root / 'tasks' / target['task_id'] / 'task.json'
        item['task_manifest'] = _ref(task_path, root)
        staged.append(item)
    evidence = list({item['path']: item for item in evidence}.values())
    manifest = {'schema_version': 2, 'manifest_type': 'PREPARED_ROUND',
                'experiment_id': compiled['config']['experiment_id'], 'round_label': round_label,
                'prepared_id': compiled['prepared_id'],
                'inputs': {'user_config': compiled['config_ref'], 'sources': compiled['sources'],
                           'evaluation': compiled['config']['evaluation']},
                'images': compiled['images'], 'evidence': evidence,
                'target_count': len(staged), 'targets': staged}
    if testcase_indexes:
        manifest['testcase_indexes'] = testcase_indexes
    _validate(manifest, 'prepared-round-v2.schema.json')
    write_json(frozen_path, manifest, refuse_overwrite=True)
    (round_root / 'ledger.jsonl').touch(exist_ok=True)
    return load_round(frozen_path, root=root, expected=compiled)


def load_round(path: Path, *, root: Path = ROOT, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    root = root.resolve(); path = path.resolve()
    manifest = _read(path)
    _validate(manifest, 'prepared-round-v2.schema.json')
    compiled = expected or compile_round(root / manifest['inputs']['user_config']['path'], manifest['round_label'], root=root)
    if (path != root / 'sdd-bench/scrapy-sdd/batch/runs' / compiled['prepared_id'] / 'prepared-round.json'
            or manifest['prepared_id'] != compiled['prepared_id']
            or manifest['experiment_id'] != compiled['config']['experiment_id']
            or manifest['inputs'] != {'user_config': compiled['config_ref'], 'sources': compiled['sources'],
                                      'evaluation': compiled['config']['evaluation']}
            or manifest['images'] != compiled['images']
            or manifest['target_count'] != len(compiled['targets'])):
        raise BatchError('ROUND_MANIFEST_CONFLICT', 'Frozen round differs from current pinned inputs')
    for item in manifest['evidence']:
        _pinned(root, item)
    if compiled['config']['evaluation'].get('localization_protocol') == 'testcase-v1':
        from .testcase_identity import inventory, verified_baseline
        indexes = manifest.get('testcase_indexes', {})
        expected_bases = {image['base_sha'] for image in compiled['images']}
        if set(indexes) != expected_bases:
            raise BatchError('TESTCASE_INDEX_MISSING', 'Prepared testcase indexes do not cover all bases')
        for base, ref in indexes.items():
            expected_path = path.parent / 'testcase-indexes' / (base + '.json')
            if _pinned(root, ref) != expected_path:
                raise BatchError('TESTCASE_INDEX_PATH', 'Validation index is outside its host-only directory')
            repository, _ = verified_baseline(root / 'sdd-bench/scrapy-sdd', base)
            if _read(expected_path) != inventory(repository, base):
                raise BatchError('TESTCASE_INDEX_CONFLICT', 'Frozen index no longer matches baseline')
    for original, staged in zip(compiled['targets'], manifest['targets']):
        if {k: v for k, v in original.items() if k != 'task_manifest'} != {k: v for k, v in staged.items() if k != 'task_manifest'}:
            raise BatchError('ROUND_TARGET_CONFLICT', 'Frozen target identity differs from config')
        task_path = root / staged['task_manifest']['path']
        if task_path != path.parent / 'tasks' / original['task_id'] / 'task.json':
            raise BatchError('ROUND_TASK_PATH_INVALID', 'Task is outside its round workspace')
        _pinned(root, staged['task_manifest'])
        if staged['task_manifest']['sha256'] != original['task_manifest']['sha256']:
            raise BatchError('ROUND_TASK_CONFLICT', 'Staged task differs from pinned source')
    return manifest
