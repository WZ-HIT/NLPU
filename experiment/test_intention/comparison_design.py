"""TI-14 preimplementation design. Writes plans only; no execution API."""
from itertools import permutations
import argparse
import hashlib
import json
from pathlib import Path

from .static import write
from .coverage_audit import ROOT, STORE


def design(original, split_path, audit_path, destination):
    if destination.exists():
        raise ValueError('Refusing to overwrite preregistration')
    read = lambda p: json.loads(p.read_text())
    audit = read(audit_path/'summary.json')
    if audit['status'] != 'PASS':
        raise ValueError('TI-13 audit must pass before fixing this design')
    scope, split = read(original/'scope.json'), read(split_path)
    prs, methods = split['development_prs'], ['openspec', 'speckit', 'cc-sdd']
    task_ids = list(dict.fromkeys(t['task_id'] for t in scope['targets']))
    if task_ids != [f'scrapy__scrapy__pr{pr}' for pr in prs] or set(prs) & set(split['held_out_prs']):
        raise ValueError('Public split differs from source scope')
    public_tasks = {}
    for target in scope['targets']:
        public_tasks[target['task_id']] = {'base_sha': target['base_sha'],
                                         'historical_task_manifest_reference': target['task_manifest']}
    orders = list(permutations('ABC'))
    schedule = []
    for pi, pr in enumerate(prs):
        for mi, method in enumerate(methods):
            block = pi*len(methods)+mi
            for position, group in enumerate(orders[block % len(orders)]):
                task_id = f'scrapy__scrapy__pr{pr}'
                schedule.append(dict(order=len(schedule)+1, block=block, position=position+1,
                    pr=pr, task_id=task_id, base_sha=public_tasks[task_id]['base_sha'],
                    method=method, group=group, repeat=1, pilot=pi < 3))
    config = dict(version='ti14-matched-comparison-v1', fixed_on='2026-11-04', timezone='Asia/Shanghai',
        status='DESIGN_FIXED_EXECUTION_DISABLED', execution_allowed=False, model_calls=0,
        interpretation='Development comparison only; no generalization claim.',
        scope=dict(development_prs=prs, independent_prs=split['held_out_prs'],
                   independent_execution=False, pilot_prs=prs[:3], formal_prs=prs,
                   repetitions=1, pilot_included_if_all_bytes_and_protocol_match=True,
                   pilot_target_count=27, full_target_count=270, methods=methods),
        groups={
            'A': dict(name='No TI', inputs=['PR title/body', 'public base'], material='none'),
            'B': dict(name='Static facts', inputs=['PR title/body', 'public base', 'static facts/navigation/reader'],
                      material='same static fields and source identities as C; no model-generated text or derived index statistics'),
            'C': dict(name='Static plus semantics', inputs=['PR title/body', 'public base', 'same static material as B',
                      'accepted generated semantics and explicitly marked fallbacks'], material='B plus declared semantic fields')},
        semantic_fields=['summary', 'operations', 'inputs', 'environment_mock', 'scenarios', 'uncertainties'],
        contrasts=dict(primary='C-B', secondary=['B-A', 'C-A'],
                       estimand='Total availability effect, including retrieval, reading and reasoning changes.',
                       optional_coverage_only_group=False, optional_prompt_only_group=False,
                       historical_results='descriptive context only; never replace matched A'),
        held_constant=['PR text/base/test identity/labels', 'three SDD workflows', 'model/profile/catalog',
                       'runtime/image/tool layer', 'validator code/schema/version', 'common judgment rules',
                       'draft/finalization/diagnostic rules', 'rollout/time/retries', 'scoring implementation'],
        reader=dict(default_bytes=6000, max_bytes=12000, default_items=8, max_items=25,
                    matching='same matching algorithm, weights, tie-breaks and pagination in B/C',
                    statistics='rebuild from each allowed corpus; corpus differences are part of treatment',
                    navigation='same static file tree and source relations; all tests remain searchable',
                    derived_semantic_navigation='not enabled in v1; no operation clusters or generated file themes',
                    source_comments='original comments/docstrings remain available to every group'),
        runtime=dict(model='deepseek-flash', effort='high', rollout_limit_tokens=100000,
                     timeout_seconds=2700, prefill_weight=1.0, sampling_weight=1.0,
                     formal_attempts_per_target=1, automatic_retries=False,
                     seed='not exposed by current profile; no invented provider seed',
                     concurrency=3, schedule='dispatch in schedule.json order, up to three active independent targets; no block completion barrier'),
        execution_plan=dict(order='schedule.json fixes dispatch order; record actual start/end times and interruptions',
                            partial_scope='requires preregistration revision before calls, never choose after seeing scores',
                            pilot='first three PRs in original public order; smoke validation, not representative task sampling',
                            stop='budget/credential/isolation/source mismatch: stop dispatch, retain in-flight and completed outcomes',
                            scoring_barrier='all declared targets terminal and predictions sealed before any new host scoring',
                            pilot_scoring='if pilot scored early, formal plan requires a new revision; cannot quietly pool pilot-adapted runs'),
        metrics=dict(primary='Mean over the three SDD method-level macro recalls on positive PRs; failures score zero',
                     primary_contrast='C-B', secondary=['per-SDD macro/micro P/R/F1', 'TP/FP/FN and predicted/invalid counts',
                         'completion rate and direct failure reasons on all PRs', 'at-least-one/all-recalled/exact-set counts',
                         'negative PR: correct empty/false alarm/run failure', 'per-PR paired differences',
                         'scoped file metrics with explicit label source/denominator'],
                     failures='positive task: P/R/F1=0, TP=FP=0,FN=gold_count; sealed draft only, no salvage scoring',
                     empty_success='positive PR: zero P/R/F1; negative PR: separate successful correct-empty category',
                     invalid='same existing source identity resolution and FP rule; never auto-drop invalid candidates',
                     subset='common-success subset auxiliary only; primary keeps all tasks'),
        uncertainty=dict(unit='paired PR cluster with all groups/SDDs/repeats kept together',
                         bootstrap_replicates=10000, analysis_seed=20261103, confidence=.95,
                         interval='percentile paired bootstrap, positive PR resampling for primary recall',
                         multiple_comparisons='one prespecified primary C-B contrast; other intervals descriptive',
                         limitations='single model run; intervals describe PR sampling variation, not provider rerun variation'),
        decision=dict(support='primary recall delta positive with 95% lower bound above zero; aggregate macro F1 and completion not lower',
                      mixed='recall up but F1/completion down: tradeoff, no unqualified improvement claim',
                      uncertain='interval spans zero: insufficient evidence; preserve direction and counts',
                      no_benefit='recall nonpositive: no benefit observed under this protocol',
                      per_sdd='always report all three; do not select only the best method',
                      exploratory='all first30 findings are development results'),
        budget=dict(pilot_rollout_upper_bound=2700000, full_rollout_upper_bound=27000000,
                    remaining_after_identical_pilot=24300000, budget_type='rollout cap, not currency or provider-token total',
                    paid_detection_scope_authorized=False, detection_currency_budget=None,
                    generation_budget='separate TI-17 plan, not authorized here',
                    cost_reporting='generation/detection separate; provider usage/cached input/missing usage separate; no byte-proportional token allocation'),
        prelaunch_requirements=['TI-15..19 recovery/generation/quality acceptance or explicit partial-coverage revision',
                                'TI-20..23 source-sensitive reasoning, same across groups',
                                'TI-24 material isolation including actual DBs/index statistics',
                                'TI-25 offline/isolation/fault checks',
                                'exact public input/material/code/image/model/validator hashes frozen in execution manifest',
                                'TI-26/27 actual paid scope and currency boundary determined'],
        coverage_at_design={k:audit[k] for k in ('base_count','test_records','status_counts','packet_reason_counts')},
        unresolved=['future repaired C material version and actual coverage', 'semantic quality audit outcome',
                    'final implementation/execution manifest hashes', 'generation and detection monetary budgets'],
        no_labels_read=True, no_independent_labels_read=True)
    destination.mkdir(parents=True)
    write(destination/'design.json', config)
    write(destination/'schedule.json', schedule)
    write(destination/'public-task-references.json', public_tasks)
    references = [original/'scope.json', split_path, audit_path/'summary.json', audit_path/'completion.json',
                  ROOT/'experiment/TEST_INTENTION_NEXT_TASKS.md', ROOT/'experiment/TEST_INTENTION_P0_DESIGN.md',
                  ROOT/'experiment/TEST_INTENTION_TI13_COVERAGE_RESULTS.md',
                  ROOT/'experiment/TEST_INTENTION_TI14_COMPARISON_DESIGN.md',
                  STORE/'p2-first30-v1/runtime-lock.json']
    implementation = [*sorted((ROOT/'experiment/test_intention').glob('*.py')),
                      ROOT/'sdd-bench/scrapy-sdd/batch/stages.py',
                      ROOT/'sdd-bench/scrapy-sdd/batch/testcase_identity.py',
                      ROOT/'sdd-bench/scrapy-sdd/batch/testcase_metrics.py',
                      *sorted((ROOT/'sdd-bench/scrapy-sdd/batch/public_detect').glob('*'))]
    write(destination/'preimplementation-sources.json', {'note': 'Design-time evidence, not future executable lock.',
        'sha256': {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in dict.fromkeys(references+implementation) if p.is_file()}})
    write(destination/'completion.json', {'status': 'DESIGN_COMPLETE', 'execution_allowed': False,
          'output_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(destination.iterdir()) if p.is_file()}})
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    config = design(STORE/'first30-v1', STORE/'p0-20261103-v1/data-split.json',
                    args.audit.resolve(), args.output.resolve())
    print(json.dumps({'status': config['status'], 'execution_allowed': False,
                      'planned_targets': config['scope']['full_target_count']}))


if __name__ == '__main__':
    main()
