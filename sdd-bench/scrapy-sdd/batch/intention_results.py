"""Read-only live presentation for an externally controlled TI experiment.

Only a registry-pinned plan, preparation summaries and the controller journal are
read. Requests never invoke preparation, evaluation, model dispatch or retries.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

PROVIDER = 'test-intention-run-v1'
METHODS = ('openspec', 'speckit', 'cc-sdd')
STATES = {'PENDING': '待运行', 'DETECT_RUNNING': '运行中',
          'DETECT_SEALED': '已封存', 'FAILED': '失败', 'BLOCKED': '阻塞'}
STAGES = {
    'PREPARING_NO_MODELS': '准备中：逐 PR 检查',
    'PREPARED_NO_MODELS': '准备完成，等待离线验收',
    'CONTAINER_PROBES_NO_MODELS': '离线验收：容器入口检查',
    'ACCEPTED_READY_FOR_AUTHORIZED_D_RUN': '离线验收完成，等待正式执行',
    'RUNNING_AUTHORIZED_D_ONLY': '正式实验运行中',
    'ALL_TERMINAL_SCORING_ON_HOST': '目标全部终结，宿主机评分中',
    'COMPLETE': '实验完成', 'STOPPED_INSPECT_REQUIRED': '已停止，需核查',
}


def read(path, default=None):
    if path.is_symlink():
        raise ValueError('实验展示来源不能是符号链接')
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def alive(process):
    try:
        fields = Path(f"/proc/{int(process['pid'])}/stat").read_text().split(') ', 1)[1].split()
        return fields[0] != 'Z' and fields[19] == str(process['start_ticks'])
    except (KeyError, ValueError, OSError, IndexError):
        return False


def snapshot(bench, entry):
    """Return an allowlisted view; no raw journal details, paths or gold."""
    try:
        return _snapshot(entry)
    except (KeyError, TypeError, AttributeError, sqlite3.Error) as error:
        raise ValueError('TI 实验进度记录无效或暂不可读') from error


def _snapshot(entry):
    root = Path(entry['run_root'])
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError('TI 实验目录无效')
    path = root / 'plan.json'
    if path.is_symlink():
        raise ValueError('实验计划不能是符号链接')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry.get('plan_sha256'):
        raise ValueError('TI 实验计划与登记哈希不一致')
    plan = json.loads(raw)
    rows = plan['targets']
    expected = {(r['group'], r['task_id'], r['method']) for r in rows}
    prs = plan['prs']
    if (plan['version'] != 'dynamic-d-run-v1' or plan['groups'] != ['D']
            or len(rows) != len(expected) or len(rows) != len(prs)*len(METHODS)
            or {r['pr'] for r in rows} != set(prs)
            or any(r['group'] != 'D' or r['method'] not in METHODS
                   or not re.fullmatch(r'[a-zA-Z0-9_.-]+', r['task_id']) for r in rows)
            or any({r['method'] for r in rows if r['pr'] == pr} != set(METHODS) for pr in prs)):
        raise ValueError('TI 实验目标范围不完整')
    journal = {}
    ledger = root / 'ledger.sqlite3'
    if ledger.is_symlink():
        raise ValueError('实验 journal 不能是符号链接')
    if ledger.exists():
        with sqlite3.connect(ledger.as_uri()+'?mode=ro', uri=True, timeout=2) as db:
            journal = {k: (s, n) for k, s, n in db.execute('SELECT key,state,starts FROM targets')}
    keys = {':'.join((r['group'], r['task_id'], r['method'])) for r in rows}
    if (set(journal)-keys or any(s not in STATES or type(n) is not int or n not in (0, 1)
                                for s, n in journal.values())):
        raise ValueError('TI journal 与计划范围不一致')
    runs = root / 'execution-root/sdd-bench/scrapy-sdd/batch/runs'
    rounds = list(runs.glob('round-*'))
    if len(rounds) > 1:
        raise ValueError('TI 准备目录不唯一，无法确认进度')
    tasks = rounds[0]/'tasks' if rounds else None
    preparation = {}
    for row in rows:
        if row['task_id'] not in preparation:
            summary = read(tasks/row['task_id']/'preflight-summary.json') if tasks else None
            preparation[row['task_id']] = '已检查' if summary else '待检查'
    targets = [dict(pr=r['pr'], method=r['method'],
                    state=journal.get(':'.join((r['group'], r['task_id'], r['method'])), ('PENDING', 0))[0],
                    preparation=preparation[r['task_id']]) for r in rows]
    counts = Counter(t['state'] for t in targets)
    stage = read(root/'execution-status.json', {}).get('stage', 'UNKNOWN')
    complete = read(root/'completion.json')
    completed = bool(complete and complete.get('status') == 'COMPLETE')
    if completed and (complete.get('targets') != len(rows)
                      or sum(counts[s] for s in ('DETECT_SEALED', 'FAILED', 'BLOCKED')) != len(rows)):
        raise ValueError('完成记录与目标终态数量不一致')
    process_alive = alive(read(root/'workflow-process.json', {}))
    if stage == 'STOPPED_INSPECT_REQUIRED':
        label = STAGES[stage]
    elif completed:
        label = '实验完成'
    elif not process_alive:
        label = '控制进程已退出，需核查'
    else:
        label = STAGES.get(stage, '准备中')
    sealed = counts['DETECT_SEALED']
    failed = counts['FAILED']+counts['BLOCKED']
    return {'experiment_id': entry['id'], 'at': datetime.now(timezone.utc).isoformat(),
            'stage': stage, 'label': label, 'workflow_alive': process_alive,
            'complete': completed,
            'expected': len(rows), 'prs': prs, 'methods': list(METHODS),
            'prepared': sum(v == '已检查' for v in preparation.values()),
            'formal_starts': sum(n for s, n in journal.values()),
            'sealed': sealed, 'failed': failed, 'terminal': sealed+failed,
            'running': counts['DETECT_RUNNING'], 'pending': counts['PENDING'],
            'targets': targets, 'model': plan['model'], 'effort': plan['effort'],
            'rollout_per_target': plan['rollout_per_target'],
            'max_parallel': plan['max_parallel'], 'timeout_seconds': plan['timeout_seconds']}


def state_label(state, doc):
    if state == 'DETECT_RUNNING' and not doc['workflow_alive']:
        return '记录为运行中，进程需核查'
    return STATES[state]


def summary_text(doc):
    return (f"{doc['label']}；准备检查 {doc['prepared']}/{len(doc['prs'])} PR；"
            f"正式终态 {doc['terminal']}/{doc['expected']}；已封存 {doc['sealed']} · "
            f"失败/阻塞 {doc['failed']} · 运行记录 {doc['running']} · 待运行 {doc['pending']}")


def live_script(entry):
    identifier = json.dumps(entry['id'])
    return '''<script>
(() => {
const id=IDENTIFIER, scope=document.querySelector('[data-ti-id="'+id+'"]');
if(!scope)return;
const put=(key,value)=>{const n=scope.querySelector('[data-ti="'+key+'"]');if(n)n.textContent=value;};
const names={PENDING:'待运行',DETECT_RUNNING:'运行中',DETECT_SEALED:'已封存',FAILED:'失败',BLOCKED:'阻塞'};
let busy=false;
async function tick(){
 if(busy||document.hidden)return;busy=true;
 try{
  const r=await fetch('/api/intention-results/'+encodeURIComponent(id),{cache:'no-store'});
  if(!r.ok)throw Error('进度读取失败（HTTP '+r.status+'），请刷新核查');
  const d=await r.json();
  put('summary',d.label+'；准备检查 '+d.prepared+'/'+d.prs.length+' PR；正式终态 '+d.terminal+'/'+d.expected+'；已封存 '+d.sealed+' · 失败/阻塞 '+d.failed+' · 运行记录 '+d.running+' · 待运行 '+d.pending);
  put('heartbeat',new Date(d.at).toLocaleString());put('error','');
  put('starts',d.formal_starts+'/'+d.expected);
  for(const [key,value,total] of [['prepare',d.prepared,d.prs.length],['formal',d.terminal,d.expected]]){
   const n=scope.querySelector('[data-ti-bar="'+key+'"]');if(n)n.style.width=(100*value/Math.max(1,total))+'%';
  }
  for(const t of d.targets){
   const n=scope.querySelector('[data-ti-target="'+t.pr+':'+t.method+'"]');
   if(n)n.textContent=t.state==='DETECT_RUNNING'&&!d.workflow_alive?'记录为运行中，进程需核查':names[t.state];
   const p=scope.querySelector('[data-ti-preparation="'+t.pr+'"]');if(p)p.textContent=t.preparation;
  }
  const done=scope.querySelector('[data-ti="completion"]');
  if(done)done.textContent=d.complete?'实验完成，目标均已终结。':'目标封存与最终评分完成后，再分析定位质量。';
 }catch(e){put('error',e.message+'；以上保留上次状态');}finally{busy=false;}
}
setInterval(tick,15000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick();});tick();
})();
</script>'''.replace('IDENTIFIER', identifier)


def homepage_row(viewer, ui, bench, entry):
    esc = ui.esc
    try:
        doc = snapshot(bench, entry)
        status = summary_text(doc)
    except (ValueError, OSError) as error:
        status = '无法读取：'+str(error)
    return (f'<div class="round-row" data-ti-id="{esc(entry["id"])}" data-search-row="{esc(entry["name"].lower())}">'
            f'<div class="name"><h2>{esc(entry["name"])}</h2><div class="secondary" data-ti="summary">{esc(status)}</div>'
            '<div class="error" data-ti="error" role="status"></div></div>'
            f'<a href="/round/{esc(entry["id"])}">查看实时进度 →</a></div>'+live_script(entry))


def round_page(viewer, ui, bench, entry):
    doc = snapshot(bench, entry)
    esc = ui.esc
    content = (f'<section data-ti-id="{esc(entry["id"])}"><h1>{esc(entry["name"])}</h1>'
               f'<p>{len(doc["prs"])} PR × 3 SDD · {doc["expected"]} 个正式目标</p>'
               f'<p data-ti="summary">{esc(summary_text(doc))}</p>'
               '<p class="error" data-ti="error" role="status"></p>'
               f'<p>准备进度（PR）</p><div class="progress-bar"><span data-ti-bar="prepare" style="width:{100*doc["prepared"]/len(doc["prs"]):.2f}%"></span></div>'
               f'<p>正式实验进度（终态目标）</p><div class="progress-bar"><span data-ti-bar="formal" style="width:{100*doc["terminal"]/doc["expected"]:.2f}%"></span></div>'
               f'<p>已启动正式任务：<strong data-ti="starts">{doc["formal_starts"]}/{doc["expected"]}</strong></p>'
               '<p class="muted">每 15 秒更新 · 最近读取：<span data-ti="heartbeat">'+esc(doc['at'])+'</span></p>'
               '<p data-ti="completion">目标封存与最终评分完成后，再分析定位质量。</p>'
               '<p class="pill">准备检查不计入正式任务；终态包括已封存、失败与阻塞。已封存表示执行结束，定位质量由宿主机最终报告评估。</p>')
    rows = []
    for pr in doc['prs']:
        selected = {t['method']: t for t in doc['targets'] if t['pr'] == pr}
        values = [str(pr), f'<span data-ti-preparation="{pr}">{esc(selected[METHODS[0]]["preparation"])}</span>']
        values += [f'<span data-ti-target="{pr}:{m}">{esc(state_label(selected[m]["state"], doc))}</span>' for m in METHODS]
        rows.append(ui.cells(values).replace('<tr>', f'<tr data-search-row="{pr}">', 1))
    content += '<h2>PR 与方法进度</h2>'+ui.search()+ui.table(['PR', '准备检查', *METHODS], rows)
    protocol = (f'{doc["model"]} / {doc["effort"]}；每目标 rollout {doc["rollout_per_target"]:,}；'
                f'超时 {doc["timeout_seconds"]} 秒；并发 {doc["max_parallel"]}；零自动重试。')
    content += '<details class="panel"><summary>实验范围与运行条件</summary><p>'+esc(protocol)+'</p><p>D = C 的 TI 加入动态调用图与两层共享信息。C 为历史结果，本轮只运行 D，不能据此认定为同期受控比较。</p></details></section>'
    return ui.page(viewer, entry['name'], [('overview', 'D 组实时进度', content)]).replace('</body>', live_script(entry)+'</body>', 1)
