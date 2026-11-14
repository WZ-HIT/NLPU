"""Host-only Detect v3: unchanged legacy files + scoped files + testcases.

Derived reports live separately from detect-metrics-v2 and never mutate seals.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator
from .core import BatchError, canonical_sha256, sha256_file, write_json
from . import detect_metrics
from .evaluator import score_ranked
from .gold_audit import verify_detection
from .prepare import _pinned
from .result_view import _load_source, build as result_view
from .testcase_identity import inventory, resolve, verified_baseline, PROTOCOL
from .testcase_labels import build_labels

VERSION = 'detect-metrics-v3'
REPORT_DIR = 'Log/reports/testcase-metrics'


def score(predicted: list[str], gold: list[str], invalid: Sequence[str] = ()) -> dict[str, Any]:
    result = score_ranked(predicted, gold)
    # Invalid identities incur false positives; duplicates never multiply weight.
    result['fp'] += len(set(invalid))
    result['predicted_count'] += len(set(invalid))
    result['invalid_count'] = len(set(invalid))
    result['precision'] = result['tp'] / result['predicted_count'] if result['predicted_count'] else 0.0
    p, r = result['precision'], result['recall']
    result['f1'] = 2*p*r/(p+r) if p+r else 0.0
    return {k: result[k] for k in ('tp', 'fp', 'fn', 'predicted_count', 'gold_count', 'invalid_count', 'precision', 'recall', 'f1')}


def measure(candidates: list[dict[str, Any]] | None, index: dict[str, Any], labels: dict[str, Any],
            *, protocol: str, state: str) -> dict[str, Any]:
    prediction = resolve(candidates or [], index)
    result = {'status': 'OK', 'prediction': prediction, 'testcase': None, 'scoped_file': None}
    if not labels['complete']:
        result['status'] = 'LABELS_INCOMPLETE'
        return result
    failed = state in {'FAILED', 'BLOCKED'}
    if not failed and state not in {'DETECT_SEALED', 'EVALUATED'}:
        result['status'] = 'PENDING'
        return result
    if not failed and candidates is None:
        result['status'] = 'EVIDENCE_INVALID'
        return result
    if not failed and protocol != PROTOCOL and (not candidates or any(not c.get('symbols') for c in candidates)):
        # Old protocol did not require method predictions, including empty output.
        result['status'] = 'HISTORICAL_UNSCORABLE'
        return result
    gold = labels['testcases']
    if not gold:
        result['status'] = 'NO_POSITIVE_GOLD'
        result['false_alarm_count'] = len(prediction['testcases']) + len(prediction['invalid'])
        return result
    if failed:
        prediction = resolve([], index)
        result['prediction'] = prediction
    result['status'] = 'FAILED_ZERO' if failed else ('HISTORICAL_RESCORED' if protocol != PROTOCOL else 'OK')
    result['testcase'] = score(prediction['testcases'], gold, prediction['invalid'])
    gold_files = sorted({value.split('::', 1)[0] for value in gold})
    result['scoped_file'] = score(prediction['files'], gold_files)
    return result


def summarize(rows: list[dict[str, Any]], level: str, *, successful_only: bool = False) -> dict[str, Any]:
    selected = [r[level] for r in rows if r[level] is not None and (not successful_only or r['status'] != 'FAILED_ZERO')]
    totals = {k: sum(m[k] for m in selected) for k in ('tp', 'fp', 'fn', 'predicted_count', 'gold_count', 'invalid_count')}
    tp, fp, fn = (totals[k] for k in ('tp', 'fp', 'fn'))
    p = tp/(tp+fp) if tp+fp else 0.0
    r = tp/(tp+fn) if tp+fn else 0.0
    return {'scored_count': len(selected), **totals,
            'precision_micro': p if selected else None, 'recall_micro': r if selected else None,
            'f1_micro': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else (0.0 if selected else None),
            **{k+'_macro': sum(m[k] for m in selected)/len(selected) if selected else None for k in ('precision','recall','f1')}}


def _raw_records(config: dict[str, Any], root: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    approved = config.get('approved_plans') or [config.get('approved_plan')]
    if not approved or any(p is None for p in approved):
        raise BatchError('TESTCASE_SOURCE_UNPINNED', 'Method labels require approved plans with pinned raw records')
    records, refs, file_cache = {}, [], {}
    for plan_ref in approved:
        plan_path = _pinned(root, plan_ref)
        plan = json.loads(plan_path.read_text())
        reference = {k: plan['inputs']['raw'][k] for k in ('path','sha256')}
        raw_path = _pinned(root, reference)
        refs.extend([{'path': plan_ref['path'], 'sha256': plan_ref['sha256']}, reference])
        if reference['path'] not in file_cache:
            grouped = {}
            for line in raw_path.read_text().splitlines():
                if line.strip():
                    raw = json.loads(line)
                    key = (raw.get('repo'), raw.get('pr_id'))
                    grouped.setdefault(key, []).append(raw)
            file_cache[reference['path']] = grouped
        for task in plan['tasks']:
            matches = file_cache[reference['path']].get((task['repository'], task['pr_id']), [])
            if len(matches) != 1:
                raise BatchError('TESTCASE_RAW_AMBIGUOUS', 'Expected one paired raw record', task_id=task['task_id'])
            existing = records.get(task['task_id'])
            if existing is not None and canonical_sha256(existing) != canonical_sha256(matches[0]):
                raise BatchError('TESTCASE_SOURCE_CONFLICT', 'Sources disagree on a raw record')
            records[task['task_id']] = matches[0]
    return records, sorted({r['path']: r for r in refs}.values(), key=lambda r:r['path'])



def compute(bench: Path, batch_id: str) -> dict[str, Any]:
    """Read-only, deterministic, gold strictly on host; keep current target keys."""
    bench = bench.resolve(); root = bench.parents[1]
    detect_metrics._validate_batch_id(batch_id)
    viewer = detect_metrics.module(bench)
    experiment = detect_metrics._batch_experiment(viewer, bench, batch_id)
    config, targets, _ = _load_source(experiment.config_path, bench, root)
    indexed = result_view(experiment.config_path, bench, root)
    legacy = detect_metrics.compute(bench, batch_id)
    if legacy['result_view_sha256'] != indexed['view_sha256']:
        raise BatchError('TESTCASE_INPUT_CHANGED', 'Ledger changed between the two metric views')
    from .orchestrator import Ledger, _latest
    ledger_path = root / indexed['ledger']['path']
    events = Ledger(ledger_path, batch_id, bench/'schemas/batch-ledger-event-v1.schema.json').read()
    latest = _latest(events)
    legacy_rows = {r['target_key']: r for r in legacy['rows']}
    raw_records, source_refs = _raw_records(config, root)
    expected_protocol = config.get('evaluation', {}).get('localization_protocol', 'file-v1')
    caches, tasks, rows = {}, {}, []
    for target in targets:
        if target['stage'] != 'detect':
            continue
        from .orchestrator import target_key
        key = target_key(target); item = indexed['targets'][key]
        task_id = target['task_id']
        task_path = target['task_manifest']
        public = json.loads(task_path.read_text())
        base = public['baseline']['base_sha']
        if base not in caches:
            repository, ref = verified_baseline(bench, base)
            caches[base] = (inventory(repository, base), ref)
        index, baseline_ref = caches[base]
        if task_id not in tasks:
            labels = build_labels(raw_records[task_id], index)
            tasks[task_id] = {'base_sha': base, 'baseline_lock': baseline_ref, 'index': index, 'labels': labels}
        labels = tasks[task_id]['labels']
        candidates = None; evidence_error = None; protocol = expected_protocol
        if item['state'] in {'DETECT_SEALED','EVALUATED'}:
            try:
                execution = root / item['execution_path']
                path = execution / 'detection-manifest.json'
                if path.is_symlink() or execution.is_symlink():
                    raise BatchError('TESTCASE_EVIDENCE_UNSAFE', 'Detection evidence is unsafe')
                manifest = json.loads(path.read_text())
                verify_detection(manifest, bench/'schemas/detection-v1.schema.json', task_id, target['method'], base,
                                 sha256_file(task_path.parent/'experiment-inputs/task.md'))
                if manifest['producer']['run_id'] != target['run_id']:
                    raise BatchError('TESTCASE_RUN_MISMATCH', 'Detection run identity differs')
                protocol = manifest.get('localization_protocol', 'file-v1')
                if expected_protocol == PROTOCOL and protocol != PROTOCOL:
                    raise BatchError('TESTCASE_PROTOCOL_MISMATCH', 'Frozen config and seal protocols differ')
                # Verify execution bundle and sealed-input through the existing compliance reader.
                from .reporting import Evidence, _verify_detection
                _verify_detection(target, latest[key], bench, root, Evidence(root))
                candidates = manifest['candidates']
            except (BatchError, OSError, ValueError, KeyError, TypeError) as exc:
                evidence_error = exc.code if isinstance(exc, BatchError) else 'TESTCASE_EVIDENCE_INVALID'
        measured = measure(candidates, index, labels, protocol=protocol, state=item['state'])
        if evidence_error:
            measured.update(status='EVIDENCE_INVALID', testcase=None, scoped_file=None)
        rows.append({**{k:item[k] for k in ('target_key','target_id','task_id','method','run_id','state','attempt','ledger_event','seal')},
                     'protocol': protocol, 'error_code': evidence_error, 'index_sha256': index['index_sha256'],
                     'labels_sha256': labels['labels_sha256'], 'legacy_file': legacy_rows[key]['metrics'], **measured})
    rows.sort(key=lambda r:r['target_key'])
    methods = []
    for method in detect_metrics.METHOD_ORDER:
        group = [r for r in rows if r['method']==method]
        methods.append({'method':method, 'row_count':len(group), 'statuses':dict(sorted(Counter(r['status'] for r in group).items())),
                        'testcase':summarize(group,'testcase'), 'scoped_file':summarize(group,'scoped_file'),
                        'successful_testcase':summarize(group,'testcase',successful_only=True)})
    statuses = dict(sorted(Counter(r['status'] for r in rows).items()))
    document = {'schema_version':3, 'document_type':'DETECT_LOCALIZATION_METRICS', 'metric_definition_version':VERSION,
                'batch_id':batch_id, 'protocol':expected_protocol, 'result_view_sha256':indexed['view_sha256'],
                'legacy_metric_set_sha256':legacy['metric_set_sha256'], 'legacy_file_methods':legacy['methods'],
                'source_refs':source_refs, 'tasks':tasks, 'rows':rows, 'methods':methods,
                'counts':{'target_count':len(rows), 'scored_count':sum(r['testcase'] is not None for r in rows),
                          'failed_target_count':sum(r['state'] in {'FAILED','BLOCKED'} for r in rows),
                          'unscorable_target_count':sum(r['testcase'] is None for r in rows),
                          'invalid_prediction_count':sum(len(r['prediction']['invalid']) for r in rows),
                          'duplicate_prediction_count':sum(r['prediction']['duplicate_count'] for r in rows),
                          'no_positive_false_alarm_count':sum(r.get('false_alarm_count',0) for r in rows),
                          'statuses':statuses},
                'status':'PARTIAL' if any(s not in {'OK','HISTORICAL_RESCORED','NO_POSITIVE_GOLD'} for s in statuses) else 'OK'}
    if sha256_file(ledger_path) != indexed['ledger']['sha256']:
        raise BatchError('TESTCASE_INPUT_CHANGED', 'Ledger changed during scoring; retry after the run settles')
    document['metric_set_sha256'] = canonical_sha256(document)
    return document


def validate(document: dict[str, Any], bench: Path) -> None:
    schema = json.loads((bench/'schemas/detect-metrics-v3.schema.json').read_text())
    errors = list(Draft202012Validator(schema).iter_errors(document))
    if errors:
        raise BatchError('TESTCASE_REPORT_INVALID', 'Method report schema failed', location=errors[0].json_path)
    payload = dict(document); digest = payload.pop('metric_set_sha256')
    if canonical_sha256(payload) != digest:
        raise BatchError('TESTCASE_REPORT_CHANGED', 'Method report digest differs')


def check(bench: Path, batch_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    document = compute(bench, batch_id)
    validate(document, bench)
    if not dry_run:
        path = bench / REPORT_DIR / f'{batch_id}.json'
        path.parent.mkdir(parents=True, exist_ok=True); path.parent.chmod(0o700)
        write_json(path, document); path.chmod(0o600)
    return document
