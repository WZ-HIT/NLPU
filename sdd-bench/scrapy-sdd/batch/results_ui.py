"""Presentation only: explicit round membership and persistent group notes.

No scoring, model calls, evidence writes, or gold reads. The viewer supplies its
existing verified target, usage, and metric readers through ``viewer``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import html
import hashlib
import json
import os
import re
import tempfile
import threading

LOCK = threading.RLock()
SAFE = re.compile(r'[a-z0-9][a-z0-9._-]{0,127}')


class LayoutError(ValueError):
    pass


def esc(value):
    return html.escape(str(value), quote=True)


def read(path, default):
    if path.is_symlink():
        raise LayoutError('展示元数据不能是符号链接')
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise LayoutError('展示元数据无法读取') from error


def registry(bench):
    doc = read(bench / 'batch/viewer/rounds.json', {'version': 1, 'rounds': []})
    if not isinstance(doc, dict) or doc.get('version') != 1 or not isinstance(doc.get('rounds'), list):
        raise LayoutError('轮次目录版本或格式错误')
    seen_rounds, seen_members = set(), set()
    for item in doc['rounds']:
        if not isinstance(item, dict) or not SAFE.fullmatch(str(item.get('id', ''))):
            raise LayoutError('轮次展示 ID 无效')
        if item['id'] in seen_rounds:
            raise LayoutError('轮次展示 ID 重复')
        seen_rounds.add(item['id'])
        if not isinstance(item.get('name'), str) or not 1 <= len(item['name']) <= 200:
            raise LayoutError('轮次名称无效')
        if not isinstance(item.get('groups'), list) or not item['groups']:
            raise LayoutError('轮次必须明确列出执行组')
        for group in item['groups']:
            if not isinstance(group, dict) or not SAFE.fullmatch(str(group.get('batch_id', ''))):
                raise LayoutError('执行组 ID 无效')
            if group['batch_id'] in seen_members:
                raise LayoutError('同一批次不能重复归组')
            seen_members.add(group['batch_id'])
            if not isinstance(group.get('name'), str) or not 1 <= len(group['name']) <= 200:
                raise LayoutError('执行组名称无效')
    return doc['rounds']


def notes_path(bench):
    directory = bench / 'Log/viewer'
    # Never follow a writable metadata directory into evidence or elsewhere.
    for parent in (bench / 'Log', directory):
        if parent.is_symlink():
            raise LayoutError('备注目录不能是符号链接')
    return directory / 'notes.json'


def notes(bench):
    result = read(notes_path(bench), {'version': 1, 'notes': {}})
    if not isinstance(result, dict) or result.get('version') != 1 or not isinstance(result.get('notes'), dict):
        raise LayoutError('备注文件格式错误')
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in result['notes'].items()):
        raise LayoutError('备注内容格式错误')
    return result['notes']


def save_note(bench, round_id, batch_id, value, expected):
    """Atomic, serialized and optimistic writes; empty text deletes a note."""
    if not isinstance(value, str) or len(value) > 10000:
        raise LayoutError('备注最多 10000 字符')
    if not isinstance(expected, str):
        raise LayoutError('缺少备注原版本，请刷新页面')
    if not isinstance(round_id, str) or not isinstance(batch_id, str) or not SAFE.fullmatch(round_id) or not SAFE.fullmatch(batch_id):
        raise LayoutError('轮次或执行组 ID 无效')
    with LOCK:
        entry = next((r for r in registry(bench) if r['id'] == round_id), None)
        if entry is None or batch_id not in {g['batch_id'] for g in entry['groups']}:
            raise LayoutError('备注必须绑定已登记的轮次与执行组')
        values = notes(bench)
        key = round_id + '/' + batch_id
        if values.get(key, '') != expected:
            raise LayoutError('备注已在其他页面修改，请刷新后重试')
        if value.strip():
            values[key] = value
        else:
            values.pop(key, None)
        destination = notes_path(bench)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.notes-', dir=destination.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump({'version': 1, 'notes': values}, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


@dataclass
class Group:
    batch_id: str
    name: str
    experiment: object | None
    targets: list
    usage: dict
    rows: list
    metric_status: str
    protocol: str
    modified: float = 0
    error: str = ''


def whole(experiments):
    return {e.batch_id: e for e in experiments if e.source_kind == 'batch' and e.task_id_filter is None}


def metric_rows(viewer, bench, exp, targets):
    doc = viewer.testcase_metrics(bench, exp.batch_id)
    if doc is None:
        path = bench / 'Log/reports/testcase-metrics' / f'{exp.batch_id}.json'
        return [], '校验失败' if path.exists() else '未评分'
    current = {viewer._target_key(t.task_id, t.method, t.stage, t.run_id, t.mode): t for t in targets if t.stage == 'detect'}
    hashes = {t.view_sha256 for t in targets if t.view_sha256}
    if hashes and hashes != {doc['result_view_sha256']}:
        return [], '已过期'
    if len(current) != len(doc['rows']) or set(current) != {r['target_key'] for r in doc['rows']}:
        return [], '已过期'
    for row in doc['rows']:
        target = current.get(row['target_key'])
        if (target is None or (target.state, target.attempt) != (row['state'], row['attempt']) or (target.task_id,target.method,target.run_id) != (row['task_id'],row['method'],row['run_id'])
                or evidence_error(target) or (target.target_id and target.target_id != row['target_id'])
                or (target.seal and target.seal != row['seal'])):
            return [], '已过期或证据无效'
    return doc['rows'], '有效'


def snapshot_targets(viewer, bench, exp):
    """Display pages read the recorded index, not the prepare pipeline.

    Schema, self hash, pinned source/ledger/seals and latest-event bindings are
    verified. A stale index is reported unavailable; display requests never rebuild
    the preparation chain or silently trust outdated evidence.
    """
    path = exp.root / 'result-view.json'
    if not path.exists():
        source = viewer.load_json(exp.config_path) if exp.config_path else None
        if source and source.get('manifest_type') in {'PREPARED_ROUND','PREPARED_EXPERIMENT'}:
            raise LayoutError('结果索引缺失，页面不自动重新执行准备校验')
        # Pre-contract historical configs have no prepared validation chain.
        return viewer.batch_targets(exp, bench)
    from .result_view import load, target_id
    from .orchestrator import _latest
    view = load(path, bench, bench.parents[1], verify_evidence=False)
    if view['batch_id'] != exp.batch_id:
        raise LayoutError('结果索引的批次身份不一致')
    for ref in [view['source'], view['ledger'], *(r['seal'] for r in view['targets'].values() if r['seal'])]:
        source = viewer._safe_child(bench.parents[1], ref['path'])
        if source is None or source.is_symlink() or not source.is_file() or viewer.file_sha256(source) != ref['sha256']:
            raise LayoutError('结果索引引用已变化，当前记录不能作为最新状态展示')
    if exp.config_path is None or (bench.parents[1] / view['source']['path']).resolve() != exp.config_path.resolve():
        raise LayoutError('结果索引引用的输入来源不一致')
    source = viewer.load_json(exp.config_path)
    if source and source.get('manifest_type') in {'PREPARED_ROUND', 'PREPARED_EXPERIMENT'}:
        expected = {viewer._target_key(t['task_id'],t['method'],t['stage'],t['run_id'],t['mode']): target_id(t) for t in source['targets']}
        if expected != {k:r['target_id'] for k,r in view['targets'].items()}:
            raise LayoutError('结果索引与冻结目标身份不一致')
    events, error = viewer._ledger_events(exp)
    if error:
        raise LayoutError(error)
    if (view['ledger']['event_count'] != len(events) or view['ledger']['chain_tip_sha256'] != (events[-1]['event_sha256'] if events else None)):
        raise LayoutError('结果索引与 ledger 链头不一致')
    latest = _latest(events)
    targets = []
    for key in view['target_order']:
        row = view['targets'][key]
        event = latest.get(key)
        if (row['state'],row['attempt'],row['ledger_event']) != ((event['state'],event['attempt'],{'sequence':event['sequence'],'event_sha256':event['event_sha256']}) if event else ('NOT_RECORDED',None,None)):
            raise LayoutError('结果索引与最新 ledger 不一致')
        execution = viewer._safe_child(bench.parents[1],row['execution_path']) if row['execution_path'] else None
        problem = None
        if row['state'] in viewer.TERMINAL_STATES and (execution is None or execution.is_symlink() or not execution.is_dir() or row['seal'] is None):
            problem = '封存执行目录或 seal 缺失'
        targets.append(viewer.BatchTarget(row['task_id'],row['pr_id'],row['title'],row['method'],row['stage'],row['run_id'],row['mode'],row['state'],row['attempt'],execution,problem,key,row['target_id'],row['seal'],view['view_sha256']))
    return targets


def group_data(viewer, bench, entry, available, *, detail=True):
    exp = available.get(entry['batch_id'])
    if exp is None:
        return Group(entry['batch_id'], entry['name'], None, [], {}, [], '尚未准备', '未记录')
    try:
        targets = snapshot_targets(viewer, bench, exp)
        rows, status = metric_rows(viewer, bench, exp, targets) if detail else ([], '未读取')
        config = viewer.load_json(exp.config_path) if exp.config_path else {}
        protocol = (config or {}).get('inputs', {}).get('evaluation', {}).get('localization_protocol', 'file-v1')
        usage = viewer.batch_token_usage(exp, targets, bench) if detail else {}
        return Group(exp.batch_id, entry['name'], exp, targets, usage, rows, status, protocol, exp.modified)
    except (OSError, ValueError, RuntimeError) as error:
        return Group(entry['batch_id'], entry['name'], exp, [], {}, [], '证据无法核对', '未记录', exp.modified, str(error))


def round_data(viewer, bench, entry, available, *, detail=True):
    groups = [group_data(viewer, bench, g, available, detail=detail) for g in entry['groups']]
    # Group membership is explicit; overlapping PRs would double count metrics.
    seen = set()
    for group in groups:
        tasks = {t.task_id for t in group.targets}
        if tasks & seen:
            raise LayoutError('同一轮次的执行组包含重复 PR，拒绝重复汇总')
        seen.update(tasks)
    return groups


CSS = '''
[hidden]{display:none!important}.layout{display:block;max-width:1250px}.sidebar{display:none}.content{padding:30px 24px 70px}h1{font-size:30px;margin:8px 0 20px}a{color:var(--blue)}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:18px 0}.toolbar input{flex:1;min-width:180px}.toolbar input,.toolbar select,textarea,button.action{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px 12px;font:inherit}button.action{cursor:pointer}.muted{color:var(--muted)}.round-row{display:flex;align-items:center;gap:24px;padding:18px 12px;border-bottom:1px solid var(--line)}.round-row .name{flex:1;min-width:150px}.round-row h2{font-size:19px}.round-row .secondary{font-size:13px;color:var(--muted);margin-top:5px}.group-box{border:1px solid var(--line);border-radius:10px;margin:14px 0;padding:16px}.group-box h3{margin:0 0 8px}.note-text{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}.note-brief{white-space:pre-line;max-height:3.1em;overflow:hidden;color:var(--muted)}textarea{width:100%;min-height:110px;resize:vertical}.note-editor{margin-top:12px}.note-status{margin-left:12px}.error{color:var(--red)}.pill{color:var(--muted);font-size:12px}.technical{overflow-wrap:anywhere}.tabs{flex-wrap:wrap}.metric-panel[hidden],.tab-pane[hidden]{display:none}.table-wrap td{font-variant-numeric:tabular-nums}.pr-title{max-width:440px}.progress-bar{height:8px;background:var(--line);border-radius:6px;overflow:hidden;margin:12px 0}.progress-bar span{display:block;height:100%;background:var(--green)}@media(max-width:650px){.round-row{flex-wrap:wrap;gap:12px}.round-row .name{flex-basis:100%}.content{padding:20px 14px}.topbar{position:static}th,td{padding:9px}.round-row .secondary{overflow-wrap:anywhere}}
'''
JS = '''
document.querySelectorAll('[data-filter]').forEach(input=>input.addEventListener('input',filterRows));
function filterRows(){document.querySelectorAll('[data-search-row]').forEach(row=>{const q=(document.querySelector('[data-filter="search"]')?.value||'').toLowerCase();const group=document.querySelector('[data-filter="group"]')?.value||'';const state=document.querySelector('[data-filter="state"]')?.value||'';row.hidden=!(row.dataset.searchRow.includes(q)&&(!group||row.dataset.group===group)&&(!state||row.dataset[state]==='yes'));});}
document.querySelectorAll('[data-metric-controls]').forEach(box=>{box.addEventListener('change',()=>{const level=box.querySelector('[name="level"]').value,aggregation=box.querySelector('[name="aggregation"]').value;box.querySelectorAll('[data-level]').forEach(p=>p.hidden=p.dataset.level!==level||p.dataset.aggregation!==aggregation);});});
document.querySelectorAll('[data-edit-note]').forEach(button=>button.addEventListener('click',()=>{const form=button.closest('.group-box').querySelector('.note-editor');form.hidden=!form.hidden;}));
document.querySelectorAll('.note-editor').forEach(form=>form.addEventListener('submit',async event=>{event.preventDefault();const message=form.querySelector('.note-status'),button=form.querySelector('button');button.disabled=true;try{const response=await fetch('/api/note',{method:'POST',headers:{'Content-Type':'application/json','X-SDD-Viewer':'notes-v1'},body:JSON.stringify({round_id:form.dataset.round,batch_id:form.dataset.batch,text:form.querySelector('textarea').value,expected:form.dataset.expected})});const result=await response.json();if(!response.ok)throw Error(result.error||'保存失败');form.dataset.expected=form.querySelector('textarea').value.trim()?form.querySelector('textarea').value:'';const container=form.closest('.group-box');container.querySelectorAll('[data-note-value]').forEach(n=>n.textContent=form.dataset.expected||'暂无备注');message.textContent='已保存';form.hidden=true;}catch(error){message.textContent=error.message;message.classList.add('error');}finally{button.disabled=false;}}));
'''


def page(viewer, title, panes):
    tabs = ''.join(f'<button class="tab-button{" active" if i == 0 else ""}" data-tab="{key}">{esc(label)}</button>' for i, (key, label, _) in enumerate(panes))
    body = ''.join(f'<main class="tab-pane{" active" if i == 0 else ""}" id="tab-{key}">{content}</main>' for i, (key, _, content) in enumerate(panes))
    result = viewer._page_shell(title, tabs, '', body)
    return result.replace('</style>', CSS + '</style>', 1).replace('</body>', '<script>' + JS + '</script></body>', 1).replace('<div class="brand">', '<div class="brand"><a href="/">← 实验轮次</a> · ', 1)


def table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + ''.join('<th>' + esc(v) + '</th>' for v in headers) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def cells(values):
    return '<tr>' + ''.join('<td>' + str(value) + '</td>' for value in values) + '</tr>'


def evidence_error(target):
    return bool(target.error) and target.error not in {f'latest target state is {target.state}', 'target has no ledger event'}


def counts(viewer, targets):
    sealed = sum(t.state in viewer.TERMINAL_STATES and t.execution is not None and not t.error for t in targets)
    failed = sum(t.state in {'FAILED', 'BLOCKED'} or evidence_error(t) for t in targets)
    running = sum(t.state in {'DETECT_RUNNING', 'UPDATE_RUNNING'} and not evidence_error(t) for t in targets)
    return sealed, failed, running, len(targets)-sealed-failed-running


def progress(viewer, targets):
    sealed, failed, running, pending = counts(viewer, targets)
    prs = len({t.task_id for t in targets})
    return (f'<p><strong>{prs} PR · {len(targets)} 个方法目标</strong></p>'
            f'<p>已封存 {sealed} · 失败 {failed} · 运行中 {running} · 待运行 {pending}</p>'
            f'<div class="progress-bar"><span style="width:{100*sealed/max(1,len(targets)):.2f}%"></span></div>'
            '<p class="pill">运行中表示 ledger 最新状态，不代表进程存活；封存不等于评分通过。</p>')


def homepage(viewer, bench, experiments, history=False):
    entries = registry(bench)
    available = whole(experiments)
    if history:
        assigned = {g['batch_id'] for r in entries for g in r['groups']}
        items = [e for e in experiments if e.task_id_filter is None and e.batch_id not in assigned]
        rows = []
        for exp in items:
            rows.append(f'<div class="round-row" data-search-row="{esc(exp.experiment_id.lower())}"><div class="name"><h2>{esc(exp.experiment_id)}</h2><div class="secondary">{esc(viewer.stamp(exp.modified))}</div></div><a href="/experiment/{viewer.experiment_token(exp)}">查看历史结果 →</a></div>')
        content = '<h1>历史实验</h1><p class="muted">未归入完整轮次的历史批次；PR 在批次内查看。</p>' + search() + ''.join(rows)
    else:
        from . import production_results, intention_results
        production = [e for e in entries if e.get('provider') == production_results.PROVIDER]
        intention = [e for e in entries if e.get('provider') == intention_results.PROVIDER]
        rounds = [(entry, round_data(viewer, bench, entry, available, detail=False)) for entry in entries
                  if entry.get('provider') not in {production_results.PROVIDER, intention_results.PROVIDER}]
        rounds.sort(key=lambda pair: max((g.modified for g in pair[1]), default=0), reverse=True)
        rows = [intention_results.homepage_row(viewer, sys_module(), bench, entry) for entry in intention]
        rows += [production_results.homepage_row(viewer, bench, entry) for entry in production]
        for entry, groups in rounds:
            targets = [t for g in groups for t in g.targets]
            sealed, failed, running, pending = counts(viewer, targets)
            missing = sum(g.experiment is None or bool(g.error) for g in groups)
            state = '尚未完整核对' if missing else ('全部封存' if targets and sealed == len(targets) else '运行中' if running else '存在失败' if failed else '待完成')
            protocols = ' / '.join(sorted({g.protocol for g in groups}))
            time = max((g.modified for g in groups), default=0)
            rows.append(f'<div class="round-row" data-search-row="{esc((entry["name"]+" "+entry["id"]).lower())}"><div class="name"><h2>{esc(entry["name"])}</h2><div class="secondary">{esc(protocols)} · 模型 / 预算：未记录或未核验{esc(' · '+ '；'.join(g.error for g in groups if g.error))}</div></div><span>{len({t.task_id for t in targets})} PR</span><span>{esc(state)}<br><small class="muted">封存 {sealed} · 失败 {failed}</small></span><span class="muted">{esc(viewer.stamp(time)) if time else "尚未开始"}</span><a href="/round/{entry["id"]}">查看 →</a></div>')
        content = '<h1>选择实验轮次</h1><p class="muted">Scrapy · 每行是一套实验记录；本次实验与历史对照分开保存，执行组和 PR 在轮次内查看。</p><div class="toolbar"><a href="/compare">比较轮次</a><a href="/history">历史实验</a><a href="/">刷新</a></div>' + search() + ''.join(rows)
    return page(viewer, '实验轮次', [('overview', '实验轮次', content or '<p>尚未登记实验。</p>')])


def search():
    return '<div class="toolbar"><input type="search" data-filter="search" placeholder="搜索名称、PR 或标题" aria-label="搜索"></div>'


def summary_metric(rows, level, aggregation):
    selected = [r[level] for r in rows if isinstance(r.get(level), dict) and all(isinstance(r[level].get(k), (int, float)) for k in ('precision','recall','f1')) and (level != 'legacy_file' or r[level].get('scorable_count', 1) > 0)]
    if not selected:
        return [None, None, None], 0
    if aggregation == 'macro':
        return [sum(m[k] for m in selected)/len(selected) for k in ('precision', 'recall', 'f1')], len(selected)
    tp, fp, fn = (sum(m[k] for m in selected) for k in ('tp', 'fp', 'fn'))
    return [tp/(tp+fp) if tp+fp else 0.0, tp/(tp+fn) if tp+fn else 0.0, 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0], len(selected)


def metric_panel(viewer, groups, scope=None):
    targets = [t for g in groups for t in g.targets if scope is None or t.task_id in scope]
    rows = [r for g in groups for r in g.rows if scope is None or r['task_id'] in scope]
    notices = ''.join(f'<li>{esc(g.name)}：{esc(g.metric_status)}</li>' for g in groups)
    panels, compatibility = [], []
    for level in ('testcase', 'scoped_file', 'legacy_file'):
        for aggregation in ('macro', 'micro'):
            lines = []
            for method in viewer.VARIANTS:
                members = [r for r in rows if r['method'] == method]
                expected = sum(t.method == method and t.stage == 'detect' for t in targets)
                values, scored = summary_metric(members, level, aggregation)
                lines.append(cells([esc(viewer.LABEL[method]), *[viewer._rate(v) for v in values], f'{scored}/{expected}']))
            if level == 'legacy_file':
                compatibility.append('<h4>' + ('PR 宏平均' if aggregation == 'macro' else '总体微平均') + '</h4>' + table(['方法','Precision','Recall','F1','计分 / 目标'],lines))
            else:
                panels.append(f'<div class="metric-panel" data-level="{level}" data-aggregation="{aggregation}"{" hidden" if (level,aggregation) != ("testcase","macro") else ""}>' + table(['方法', 'Precision', 'Recall', 'F1', '计分 / 目标'], lines) + '</div>')
    alerts = ''.join('<li>'+esc(g.name)+'：'+esc(g.metric_status)+'</li>' for g in groups if g.metric_status != '有效')
    no_gold = sum(r.get('status') == 'NO_POSITIVE_GOLD' for r in rows)
    unavailable = sum(r.get('testcase') is None for r in rows)
    return ('<section><h3>测试方法定位指标</h3>' + ('<ul class="error">'+alerts+'</ul>' if alerts else '') + '<div data-metric-controls><div class="toolbar">'
            '<label>粒度 <select name="level"><option value="testcase">testcase 级</option><option value="scoped_file">同范围文件级</option></select></label>'
            '<label>聚合 <select name="aggregation"><option value="macro">PR 宏平均</option><option value="micro">总体微平均</option></select></label></div>' + ''.join(panels) + '</div>'
            f'<p class="pill">detect-metrics-v3 · 失败零分保留；无正目标 {no_gold} · 已报告但不计主分 {unavailable}。缺失、过期或无效报告不参与汇总，覆盖分母保留全部目标。</p>'
            '<details class="panel"><summary>历史文件级指标（兼容）</summary>' + ''.join(compatibility) + '</details><details class="panel"><summary>评分状态与口径</summary><ul>' + notices + '</ul><p>宏平均按 PR 等权；微平均合并 TP / FP / FN。无正目标及不可评分另列，不将缺失结果当零分。历史文件级保持原算法，作为兼容指标，不用于主指标跨协议比较。</p></details></section>')


def usage_document(viewer, groups, scope=None):
    aggregate, _ = viewer._token_tools()
    rows = [r for g in groups for r in g.usage.get('rows', []) if scope is None or r['task_id'] in scope]
    errors = [g.usage.get('error') or g.error for g in groups if g.usage.get('error') or g.error]
    return {'rows': rows, 'summary': aggregate(r['usage'] for r in rows), 'error': '; '.join(errors) or None}


def usage_panel(viewer, groups, scope=None):
    doc = usage_document(viewer, groups, scope)
    if doc['error']:
        return '<h3>Token 用量</h3><p class="error">用量证据无法核对：' + esc(doc['error']) + '</p>'
    aggregate, _ = viewer._token_tools()
    rows = []
    for method in viewer.VARIANTS:
        total = aggregate(r['usage'] for r in doc['rows'] if r['method'] == method)
        rows.append(cells([esc(viewer.LABEL[method]), *[viewer._token_number(total[k]) for k in ('input_tokens','cached_input_tokens','output_tokens','total_tokens')], f'{total["recorded_attempt_count"]}/{total["attempt_count"]}', esc(total['status'])]))
    return '<section><h3>Token 用量</h3><p class="pill">含失败与全部重试；不完整时为已知小计。总量 = 输入 + 输出，缓存输入包含在输入内。记录覆盖不等于完整覆盖。</p>' + table(['方法','输入','缓存输入','输出','已知合计','记录 / 尝试','状态'], rows) + '</section>'


def group_panel(viewer, bench, entry, groups):
    stored = notes(bench)
    result = '<section><h3>执行组与备注</h3>'
    for group in groups:
        value = stored.get(entry['id']+'/'+group.batch_id, '')
        target_status = progress(viewer, group.targets) if group.targets else '<p>尚未准备或证据无法核对</p>'
        group_name = '<a href="/experiment/' + viewer.experiment_token(group.experiment) + '">' + esc(group.name) + '</a>' if group.experiment else esc(group.name)
        result += f'<div class="group-box"><h3>{group_name}</h3>{target_status}'
        result += f'<p class="note-brief" data-note-value>{esc(value or "暂无备注")}</p><details><summary>完整备注</summary><div class="note-text" data-note-value>{esc(value or "暂无备注")}</div></details>'
        result += f'<button class="action" type="button" data-edit-note>编辑备注</button><form class="note-editor" data-round="{esc(entry["id"])}" data-batch="{esc(group.batch_id)}" data-expected="{esc(value)}" hidden><label>本轮本组备注<textarea maxlength="10000">{esc(value)}</textarea></label><button class="action" type="submit">保存</button><span class="note-status" role="status"></span></form></div>'
    return result + '</section>'


def pr_list(viewer, groups):
    rows = []
    for group in groups:
        for task_id in dict.fromkeys(t.task_id for t in group.targets):
            targets = [t for t in group.targets if t.task_id == task_id]
            first = targets[0]
            exp = replace(group.experiment, experiment_id=group.batch_id+'/'+task_id, task_id_filter=task_id)
            sealed, failed, running, pending = counts(viewer, targets)
            methods = [', '.join(dict.fromkeys(t.state for t in targets if t.method == method)) or '—' for method in viewer.VARIANTS]
            title = f'PR {first.pr_id}' if first.pr_id else task_id
            rows.append(f'<tr data-search-row="{esc((title+" "+first.title).lower())}" data-group="{esc(group.batch_id)}" data-failed="{"yes" if failed else "no"}" data-incomplete="{"yes" if sealed != len(targets) else "no"}">' + ''.join('<td>'+v+'</td>' for v in [esc(title), '<div class="pr-title">'+esc(first.title)+'</div>', *[esc(m) for m in methods], f'<a href="/experiment/{viewer.experiment_token(exp)}">查看 →</a>']) + '</tr>')
    options = ''.join(f'<option value="{esc(g.batch_id)}">{esc(g.name)}</option>' for g in groups)
    return ('<h2>PR 列表</h2>' + search() + '<div class="toolbar"><select data-filter="group" aria-label="执行组"><option value="">全部执行组</option>' + options + '</select><select data-filter="state" aria-label="状态"><option value="">全部状态</option><option value="failed">仅失败</option><option value="incomplete">未完成</option></select></div>' + table(['PR','标题', *[viewer.LABEL[m] for m in viewer.VARIANTS], ''], rows))


def round_page(viewer, bench, experiments, round_id):
    entry = next((r for r in registry(bench) if r['id'] == round_id), None)
    if entry is None:
        raise LayoutError('轮次未登记')
    from . import production_results, intention_results
    if entry.get('provider') == intention_results.PROVIDER:
        return intention_results.round_page(viewer, sys_module(), bench, entry)
    if entry.get('provider') == production_results.PROVIDER:
        return production_results.round_page(viewer, sys_module(), bench, entry)
    groups = round_data(viewer, bench, entry, whole(experiments))
    targets = [t for g in groups for t in g.targets]
    content = '<h1>' + esc(entry['name']) + '</h1>' + progress(viewer, targets)
    missing = [g.name for g in groups if g.experiment is None or g.error]
    if missing:
        content += '<p class="error">未就绪 / 无法核对：' + esc('、'.join(missing)) + '；计数仅覆盖已核对执行组。</p><ul>' + ''.join('<li>'+esc(g.name)+'：'+esc(g.error or '尚未准备')+'</li>' for g in groups if g.experiment is None or g.error) + '</ul>'
    content += metric_panel(viewer, groups) + usage_panel(viewer, groups) + group_panel(viewer, bench, entry, groups)
    technical = ''.join(f'<p>{esc(g.name)} · {esc(g.batch_id)} · 协议 {esc(g.protocol)}<br>{esc(g.experiment.config_path if g.experiment else "无 prepared manifest")}</p>' for g in groups)
    content += '<details class="panel technical"><summary>技术信息</summary>' + technical + '<p>模型、预算：未记录或未核验。页面不从当前运行时配置推断历史条件。</p></details>'
    return page(viewer, entry['name'], [('overview','概览',content),('prs','PR 列表',pr_list(viewer, groups))])


def batch_page(viewer, bench, exp):
    group = group_data(viewer, bench, {'batch_id': exp.batch_id, 'name': exp.experiment_id}, {exp.batch_id: exp})
    content = '<h1>' + esc(exp.experiment_id) + '</h1>' + progress(viewer, group.targets) + metric_panel(viewer, [group]) + usage_panel(viewer, [group])
    # Preserve v2-only historical file reports without pretending they are v3.
    content += '<details class="panel"><summary>历史文件级指标（v2 兼容）</summary>' + viewer._batch_detect_table(bench, exp.batch_id) + '</details>'
    return page(viewer, exp.experiment_id, [('overview','概览',content),('prs','PR 列表',pr_list(viewer, [group]))])


def pr_page(viewer, bench, exp):
    parent = replace(exp, experiment_id=exp.batch_id, task_id_filter=None)
    group = group_data(viewer, bench, {'batch_id': exp.batch_id, 'name': exp.batch_id}, {exp.batch_id: parent})
    targets = [t for t in group.targets if t.task_id == exp.task_id_filter]
    rows = [r for r in group.rows if r['task_id'] == exp.task_id_filter]
    usage = usage_document(viewer, [group], {exp.task_id_filter})
    aggregate, _ = viewer._token_tools()
    title = f'PR {targets[0].pr_id}' if targets and targets[0].pr_id else exp.task_id_filter
    summary = []
    for method in viewer.VARIANTS:
        members = [t for t in targets if t.method == method]
        row = next((r for r in rows if r['method'] == method), {})
        total = aggregate(r['usage'] for r in usage['rows'] if r['method'] == method)
        summary.append(cells([esc(viewer.LABEL[method]), esc(' / '.join(t.state for t in members) or '—'), viewer._rate((row.get('scoped_file') or {}).get('f1')), viewer._rate((row.get('testcase') or {}).get('f1')), viewer._token_number(total['total_tokens']), f'{total["recorded_attempt_count"]}/{total["attempt_count"]} · {esc(total["status"])}']))
    heading = '<h1>' + esc(title) + '</h1><p>' + esc(targets[0].title if targets else '') + '</p>'
    ancestors = [r for r in registry(bench) if exp.batch_id in {g['batch_id'] for g in r['groups']}]
    heading += '<p>' + (f'<a href="/round/{ancestors[0]["id"]}#prs">← 所属轮次</a>' if ancestors else f'<a href="/experiment/{viewer.experiment_token(parent)}#prs">← 所属批次</a>') + '</p>'
    comparison = heading + table(['方法','状态','文件 F1','testcase 级 F1','Token 用量（累计）','记录 / 尝试'], summary) + '<p class="muted">评分：' + esc(group.metric_status) + ' · 累计用量包含失败和重试。</p>'
    compatibility = '<details class="panel"><summary>历史文件级指标（v2 兼容）</summary>' + viewer._batch_pr_detect_section(bench,exp.batch_id,exp.task_id_filter) + '</details>'
    panes = [('overview', '方法比较', comparison + compatibility + '<p class="pill">Read-only view of terminal sealed artifacts. Scoring summaries contain counts only.</p>')]
    for method in viewer.VARIANTS:
        members = [t for t in targets if t.method == method]
        if not members:
            continue
        body = comparison
        body += '<h3>最新尝试</h3>'
        for target in members:
            # Existing renderer retains stage-specific artifact verification and
            # scope. Its raw JSON and transcript panels are already folded.
            rendered, _ = viewer._batch_target_html(target)
            start = rendered.find('<section><h3>Sealed manifests</h3>')
            if start < 0:
                start = rendered.find('<section><h3>Update artifacts</h3>')
            if start >= 0:
                rendered = rendered[:start] + '<details class="panel"><summary>原始日志、规划与证据</summary>' + rendered[start:].removesuffix('</article>') + '</details></article>'
            body += rendered
            latest = [r for r in usage['rows'] if r['method'] == method and r['latest'] and r['stage'] == target.stage and r['mode'] == target.mode]
            for attempt in latest:
                body += '<p>最新尝试已记录 token：' + viewer._token_number(attempt['usage']['total_tokens']) + ' · ' + esc(attempt['usage']['status']) + '</p>'
                if target.execution is None:
                    log = safe_log(viewer, bench, attempt)
                    if log is not None:
                        messages = failure_messages(viewer, log)
                        body += '<div class="failure"><h3>失败原因</h3><pre>' + esc('\n'.join(messages) or target.error or '未记录具体错误') + '</pre></div>'
                        body += '<p><a href="' + attempt_url(viewer, exp, attempt) + '">查看最新尝试日志 →</a></p>'
        attempts = [r for r in usage['rows'] if r['method'] == method and not r['latest']]
        older = ''.join(cells([esc(r['stage']), esc(r['mode'] or '—'), str(r['attempt']), esc(r['state']), viewer._token_number(r['usage']['total_tokens']), '<a href="' + attempt_url(viewer, exp, r) + '">查看日志</a>']) for r in attempts)
        body += '<details class="panel"><summary>历史尝试与证据引用（' + str(len(attempts)) + '）</summary>' + table(['阶段','模式','attempt','状态','已知 token','日志引用'], older) + '</details>'
        panes.append((method, viewer.LABEL[method], body))
    return page(viewer, bench.name + ' · ' + title, panes)


def compare_page(viewer, bench, experiments, selected):
    entries = registry(bench)
    selected = list(dict.fromkeys(selected))
    options = ''.join(f'<label><input type="checkbox" name="round" value="{esc(r["id"])}"{" checked" if r["id"] in selected else ""}> {esc(r["name"])}</label><br>' for r in entries)
    content = '<h1>比较实验轮次</h1><form method="get" action="/compare">' + options + '<button class="action">比较所选轮次（2–3 个）</button></form>'
    if not selected:
        return page(viewer,'比较轮次',[('overview','比较',content)])
    if not 2 <= len(selected) <= 3 or any(s not in {r['id'] for r in entries} for s in selected):
        raise LayoutError('请选择 2–3 个已登记轮次')
    from . import production_results, intention_results
    intention = [r for r in entries if r['id'] in selected and r.get('provider') == intention_results.PROVIDER]
    if intention:
        content += '<p>D 组进度独立展示；最终报告生成前不计算定位指标差值。C 为历史对照，不能当作同期控制组。</p>'
        for entry in intention:
            doc = intention_results.snapshot(bench, entry)
            content += '<h2>'+esc(entry['name'])+'</h2><p>'+esc(intention_results.summary_text(doc))+'</p>'
        return page(viewer, '比较轮次', [('overview', '轮次比较', content)])
    production = [r for r in entries if r['id'] in selected and r.get('provider') == production_results.PROVIDER]
    if production:
        content += '<p>两阶段定位与既有单阶段定位协议不同，使用本轮启动时冻结并核对身份的历史首批30 PR对照；不混入其他PR或文件级历史标签。</p>'
        for entry in production:
            doc = production_results.snapshot(bench, entry)
            content += '<h2>' + esc(entry['name']) + '</h2>'
            reference = next((e for e in entries if e['id'] in selected
                and e['id'] == entry.get('historical_compare_round')
                and entry.get('historical_batch_id') in {g['batch_id'] for g in e['groups']}), None)
            content += (production_results.comparison(viewer, sys_module(), doc) if reference
                        else '<p>所选组合没有已核对的成对历史报告，暂不计算差值。可在本轮详情查看已冻结的历史对照。</p>')
        return page(viewer,'比较轮次',[('overview','轮次比较',content)])
    rounds = [(r, round_data(viewer, bench, r, whole(experiments))) for s in selected for r in entries if r['id'] == s]
    scope = set.intersection(*[{t.task_id for g in groups for t in g.targets} for _, groups in rounds])
    content += f'<h3>共同 PR 范围：{len(scope)}</h3><p>包括该范围内的失败和未完成目标，指标与 token 使用同一 PR 范围。</p>'
    # Align dataset version as well as PR number. Unknown bindings cannot certify
    # comparability. Historical label/index hashes never appear in the UI.
    identities = [{(r['task_id'],r['method']):(r.get('index_sha256'),r.get('labels_sha256')) for g in gs for r in g.rows if r['task_id'] in scope} for _,gs in rounds]
    protocols = [{g.protocol for g in gs} for _,gs in rounds]
    aligned = bool(scope) and all(i == identities[0] for i in identities) and bool(identities[0]) and all(p == protocols[0] for p in protocols)
    content += '<p class="error">' + ('标签 / base 索引与协议已对齐；' if aligned else '不可认定为可比：PR 范围、base / 标签身份或协议未完全对齐；') + '模型与预算未核验，以下用于描述性对照，不自动排名。</p>'
    for entry, groups in rounds:
        content += '<section><h2>' + esc(entry['name']) + '</h2><p>协议：' + esc(' / '.join(sorted({g.protocol for g in groups}))) + ' · 模型 / 预算：未记录或未核验</p>'
        if scope:
            content += metric_panel(viewer, groups, scope) + usage_panel(viewer, groups, scope)
        else:
            content += '<p>没有共同 PR，无法比较。</p>'
        content += '<details class="panel"><summary>该轮完整范围结果</summary>' + metric_panel(viewer,groups) + usage_panel(viewer,groups) + '</details></section>'
    return page(viewer,'比较轮次',[('overview','轮次比较',content)])


def sys_module():
    import sys
    return sys.modules[__name__]


def safe_log(viewer, bench, attempt):
    relative = attempt.get('log_path')
    if not isinstance(relative, str):
        return None
    path = viewer._safe_child(bench.parents[1], relative)
    if path is None or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(bench.resolve()):
        return None
    return path


def failure_messages(viewer, log):
    value = viewer.load_text(log, viewer.MAX_JSONL)
    messages = []
    if value is None:
        return messages
    for line in value.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('type') in {'error', 'turn.failed'}:
            error = event.get('error', event.get('message', ''))
            if isinstance(error, dict):
                error = error.get('message', error.get('code', ''))
            if isinstance(error, str):
                messages.append(error)
    return messages[-5:]


def attempt_token(row):
    return hashlib.sha256((row['target_key'] + '/' + str(row['attempt'])).encode()).hexdigest()[:24]


def attempt_url(viewer, exp, row):
    return '/attempt/' + viewer.experiment_token(exp) + '/' + attempt_token(row)


def attempt_page(viewer, bench, exp, token):
    targets = snapshot_targets(viewer, bench, exp)
    if exp.task_id_filter:
        targets = [t for t in targets if t.task_id == exp.task_id_filter]
    usage = viewer.batch_token_usage(exp, targets, bench)
    row = next((r for r in usage['rows'] if attempt_token(r) == token), None)
    log = safe_log(viewer, bench, row) if row else None
    if log is None:
        raise LayoutError('找不到经 ledger 核对的尝试日志')
    messages = viewer.agent_messages(log)
    body = '<h1>尝试日志</h1><p>' + esc(row['method']) + ' · attempt ' + str(row['attempt']) + ' · ' + esc(row['state']) + '</p><p><a href="/experiment/' + viewer.experiment_token(exp) + '">← 返回 PR</a></p>'
    body += '<pre>' + esc('\n'.join(failure_messages(viewer, log))) + '</pre>'
    body += '<details class="panel"><summary>Agent 输出</summary>' + ''.join(viewer.code(m) for m in messages) + '</details>'
    return page(viewer, '尝试日志', [('overview','尝试日志', body)])


def loading_page(viewer, destination):
    """Return an immediate visible response before loading numeric reports."""
    target = json.dumps(destination).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    body = '<h1>正在读取实验记录…</h1><p>正在核对结果索引、评分和 token 记录，请稍候。</p><p class="muted">不会运行模型或重新准备实验。</p><p id="load-error" role="status"></p><button class="action" onclick="location.reload()">重新加载</button>'
    result = page(viewer, '读取实验记录', [('overview','读取中',body)])
    script = '<script>fetch(' + target + ").then(response=>{if(!response.ok)throw Error('读取失败（HTTP '+response.status+'），请重新加载。');return response.text();}).then(content=>{document.open();document.write(content);document.close();}).catch(error=>{document.querySelector('#load-error').textContent=error.message;});</script>"
    return result.replace('</body>', script + '</body>')
