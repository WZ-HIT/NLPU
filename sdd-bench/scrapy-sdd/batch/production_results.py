"""Read-only rendering of gold-free, controller-published two-phase snapshots."""
from __future__ import annotations

from collections import Counter
import datetime as dt
import hashlib
import html
import json
from pathlib import Path
import re

PROVIDER = 'production-test-v1'
METHODS = {'cc-sdd':'cc-sdd','openspec':'OpenSpec','speckit':'Spec Kit'}
STATES = {'PENDING':'待运行','RUNNING':'运行中','OK':'成功','FAILED':'失败',
          'SKIPPED':'跳过','EVIDENCE_ERROR':'证据校验失败'}
CONTROLLER = {'STARTING':'启动中','RUNNING':'运行中','EVALUATING':'预测已封存，评分中',
              'EVALUATED':'评分完成','STOPPED':'已停止，需核查'}
FORBIDDEN = {'testcase_gold','production_gold','gold_test','old_test','raw_record','gold_changes','head_sha'}


class DisplayError(ValueError):
    pass


def esc(value):
    return html.escape(str(value),quote=True)


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def snapshot(bench, entry):
    try:
        return _snapshot(bench, entry)
    except (KeyError, TypeError, AttributeError) as exc:
        raise DisplayError('两阶段结果快照结构无效') from exc


def _snapshot(bench, entry):
    relative = entry.get('snapshot','')
    if not re.fullmatch(r'Log/viewer/[a-z0-9][a-z0-9._-]*\.json',relative):
        raise DisplayError('两阶段结果快照路径无效')
    path = bench/relative
    if any(p.is_symlink() for p in (bench/'Log',bench/'Log/viewer',path)):
        raise DisplayError('两阶段结果快照不能是符号链接')
    if path.stat().st_size>16*1024*1024:
        raise DisplayError('两阶段结果快照过大')
    doc=json.loads(path.read_text())
    if not isinstance(doc, dict):
        raise DisplayError('两阶段结果快照必须是对象')
    digest=doc.pop('view_sha256',None)
    if canonical(doc)!=digest:
        raise DisplayError('两阶段结果快照哈希不匹配')
    doc['view_sha256']=digest
    if (doc.get('version')!=1 or doc.get('document_type')!='PRODUCTION_TEST_RESULTS_VIEW'
            or doc.get('experiment_id')!=entry['groups'][0]['batch_id']
            or doc.get('source_refs',{}).get('manifest_sha256')!=entry.get('manifest_sha256')):
        raise DisplayError('两阶段结果快照身份不匹配')
    def no_gold(value):
        if isinstance(value,dict):
            if FORBIDDEN.intersection(value):
                raise DisplayError('展示快照含不允许的评估内容')
            for item in value.values():no_gold(item)
        elif isinstance(value,list):
            for item in value:no_gold(item)
    no_gold(doc)
    methods=doc.get('methods',[])
    if doc.get('controller_state') not in CONTROLLER:
        raise DisplayError('两阶段控制器状态无效')
    if len(methods)!=3 or set(methods)!=set(METHODS):
        raise DisplayError('两阶段方法范围无效')
    tasks=doc.get('tasks',[])
    ids=[r['pr'] for r in tasks]
    if not ids or any(type(p) is not int or p<=0 for p in ids) or len(ids)!=len(set(ids)):
        raise DisplayError('两阶段PR范围无效')
    groups=doc.get('groups',[])
    if len(groups)!=len(ids)*3 or {(g['pr'],g['method']) for g in groups}!={(p,m) for p in ids for m in methods}:
        raise DisplayError('两阶段方法目标范围不完整')
    if any(g['state'] not in STATES or set(g['stages'])!={'production','tests'}
           or any(s['status'] not in STATES for s in g['stages'].values()) for g in groups):
        raise DisplayError('两阶段状态无效')
    updated=dt.datetime.fromisoformat(doc['updated_at'])
    doc['stale']=(dt.datetime.now(dt.timezone.utc)-updated).total_seconds()>90 and doc['controller_state'] not in ('EVALUATED','STOPPED')
    doc['counts']=dict(Counter(g['state'] for g in groups))
    return doc


def effective_state(doc):
    return '状态快照已过期，进程状态未确认' if doc['stale'] else CONTROLLER.get(doc['controller_state'],'状态未知')


def group_label(group, doc):
    if group['state']=='RUNNING':
        if doc['stale'] or doc['controller_state']=='STOPPED':return '中断／进程状态待核查'
        stage='生产定位' if group['stages']['production']['status']=='RUNNING' else '测试定位'
        return stage+'中'
    return STATES[group['state']]


def independent_tests(doc):
    return doc.get('test_search_strategy') == 'all_tests'


def protocol_description(doc):
    if independent_tests(doc):
        return ('第一轮生产文件／类／函数预测仅供人工分析，不传入第二轮；第二轮依据PR title/body与允许base，'
                '搜索全部已有测试，直接判断测试文件／testcase更新，不要求生产关联。全量索引仅从base生成，'
                '返回候选只是判断记录。更新理由可选；共享预算和时限，零自动重试。')
    return ('先定位生产文件／类／函数，再判断测试文件／testcase更新；成功空生产仍按PR描述进行第二轮。'
            '更新理由可选，零自动重试。完成组封存后跳过，部分组停止核查。')


def homepage_row(viewer,bench,entry):
    try:
        doc=snapshot(bench,entry);c=doc['counts']
        info=f'{len(doc["tasks"])} PR · {len(doc["groups"])} 组 · 生产文件／类／函数 → 测试文件／testcase'
        if independent_tests(doc):
            info=f'{len(doc["tasks"])} PR · {len(doc["groups"])} 组 · 生产定位人工材料＋独立全量测试定位'
        status=f'{effective_state(doc)}；成功 {c.get("OK",0)} · 失败 {c.get("FAILED",0)+c.get("EVIDENCE_ERROR",0)} · 待运行 {c.get("PENDING",0)}'
    except (ValueError,OSError,KeyError,TypeError) as exc:
        info='两阶段定位';status='无法读取：'+str(exc)
    return (f'<div class="round-row" data-search-row="{esc(entry["name"].lower())}">'
            f'<div class="name"><h2>{esc(entry["name"])}</h2><div class="secondary">{esc(info)}</div></div>'
            f'<span>{esc(status)}</span><a href="/round/{esc(entry["id"])}">查看 →</a></div>')


def live_script(entry,doc):
    # Reload only on a phase/state/usage change, not every heartbeat; keep notes
    # being edited and hidden tabs untouched.
    signature=lambda v: {'controller':v['controller_state'],'metrics':v['metrics_available'],
        'groups':[(g['pr'],g['method'],g['state'],[(k,s['status']) for k,s in g['stages'].items()]) for g in v['groups']],
        'usage':[v['usage'][k] for k in ('rollout_known_subtotal','recorded_stages','started_stages')]}
    initial=json.dumps(signature(doc),sort_keys=True,ensure_ascii=False)
    return '''<script>(function(){const initial=JSON.stringify('''+initial+''');
setInterval(async()=>{if(document.hidden)return;try{const response=await fetch('/api/production-results/'''+entry['id']+'''',{cache:'no-store'});if(!response.ok)return;const d=await response.json();document.querySelectorAll('[data-heartbeat]').forEach(n=>n.textContent=d.updated_at);if(d.stale){document.querySelectorAll('[data-controller-state]').forEach(n=>n.textContent='状态快照已过期，进程状态未确认');return;}const now={controller:d.controller_state,groups:d.groups.map(g=>[g.pr,g.method,g.state,Object.entries(g.stages).map(([k,s])=>[k,s.status])]),metrics:d.metrics_available,usage:[d.usage.rollout_known_subtotal,d.usage.recorded_stages,d.usage.started_stages]};if(JSON.stringify(now)!==initial&&!['INPUT','TEXTAREA'].includes(document.activeElement?.tagName))location.reload();}catch(e){}},15000);})();</script>'''


def summary(viewer,ui,doc):
    c=doc['counts'];usage=doc['usage'];b=doc['budgets']
    content=(f'<p><strong>{len(doc["tasks"])} PR · {len(doc["groups"])} 组 · 最多 {b["max_stage_runs"]} 阶段</strong></p>'
             f'<p data-controller-state>{esc(effective_state(doc))}</p>'
             f'<p>完整成功 {c.get("OK",0)} · 失败 {c.get("FAILED",0)+c.get("EVIDENCE_ERROR",0)} · '
             f'运行中 {c.get("RUNNING",0)} · 待运行 {c.get("PENDING",0)}</p>'
             f'<p class="muted">快照核对：<span data-heartbeat>{esc(doc["updated_at"])}</span> · 每15秒检查更新</p>'
             f'<p>{esc(doc["agent"])} · {esc(doc["model"])} / {esc(doc["reasoning"])} · '
             f'每组 {b["token_budget_per_pr"]:,} rollout，首轮 {b["production_token_budget"]:,}，共享 {b["deadline_seconds_per_pr"]//60} 分钟</p>'
             f'<p>加权rollout已知小计 <strong>{usage["rollout_known_subtotal"]:,}</strong> · '
             f'已返回完整usage {usage["recorded_stages"]}/{usage["started_stages"]} 个已启动阶段</p>'
             '<p class="pill">rollout=(input−cached input)+output；未知用量不当作零，不推算费用。指标在全批预测封存后统一评分。</p>')
    if doc.get('controller_error'):content+='<p class="error">'+esc(doc['controller_error'])+'</p>'
    if independent_tests(doc):
        content+='<p class="pill">'+esc(protocol_description(doc))+'</p>'
    if not doc['metrics_available']:
        return content+'<h3>定位指标</h3><p>未评分：生产文件／类／函数、测试文件与testcase指标暂为N/A。</p>'
    rows=[]
    for method in doc['methods']:
        m=doc['method_metrics'][method]
        rows.append(ui.cells([esc(METHODS[method]),f'{m["successful_groups"]}/{len(doc["tasks"])}',
            f'{m.get("successful_test_groups",m["successful_groups"])}/{len(doc["tasks"])}',
            viewer._rate(m['testcase']['macro_f1']),viewer._rate(m['testcase']['micro_f1']),
            viewer._rate(m['all_pr_micro']['testcase']['f1']),str(m['failed_no_positive_groups'])]))
    content+='<h3>最终测试定位</h3>'+ui.table(['方法','完整成功','测试轮成功','正任务macro F1','正任务micro F1','全PR micro F1','无正标签失败组'],rows)
    content+='<p class="pill">失败按冻结协议计分；无正标签任务失败后的空预测不能解释为正确负判断。</p>'
    rows=[]
    for method in doc['methods']:
        m=doc['method_metrics'][method]
        for level,name in [('file','生产文件'),('class','生产类'),('function','生产函数')]:
            a=m['production'][level]
            rows.append(ui.cells([esc(METHODS[method]),name,*[viewer._rate(a['micro_'+k]) for k in ['precision','recall','f1']],str(a['positive_tasks']),str(a['no_positive_fp'])]))
        a=m['scoped_file']
        rows.append(ui.cells([esc(METHODS[method]),'测试文件（同范围）',*[viewer._rate(a['micro_'+k]) for k in ['precision','recall','f1']],str(a['positive_tasks']),str(a['no_positive_fp'])]))
    return content+'<h3>生产定位与文件级诊断</h3>'+ui.table(['方法','粒度','Precision','Recall','F1','正任务数','无正任务误报'],rows)


def pr_table(viewer,ui,doc,entry):
    groups={(g['pr'],g['method']):g for g in doc['groups']};rows=[]
    for task in doc['tasks']:
        pr=task['pr'];labels=[group_label(groups[pr,m],doc) for m in doc['methods']]
        failed=any(groups[pr,m]['state'] in ('FAILED','EVIDENCE_ERROR') for m in doc['methods'])
        pending=any(groups[pr,m]['state'] not in ('OK','FAILED','EVIDENCE_ERROR') for m in doc['methods'])
        row=ui.cells([str(pr),esc(task['title']),*[esc(x) for x in labels],f'<a href="/production-pr/{esc(entry["id"])}/{pr}">详情 →</a>'])
        row=row.replace('<tr>',f'<tr data-search-row="{esc((str(pr)+" "+task["title"]).lower())}" data-failed="{"yes" if failed else "no"}" data-pending="{"yes" if pending else "no"}">',1)
        rows.append(row)
    filters='<div class="toolbar"><select data-filter="state" aria-label="状态筛选"><option value="">全部状态</option><option value="failed">存在失败</option><option value="pending">尚未完成</option></select></div>'
    return ui.search()+filters+ui.table(['PR','标题',*[METHODS[m] for m in doc['methods']],'操作'],rows)


def comparison(viewer,ui,doc):
    if not doc['metrics_available']:return '<p>历史对照：等待本轮全局封存与评分。</p>'
    rows=[]
    for method in doc['methods']:
        m=doc['paired_comparison'][method]['metrics']['testcase']
        rows.append(ui.cells([esc(METHODS[method]),str(m['paired_count']),viewer._rate(m['new']['macro_f1']),
            viewer._rate(m['historical']['macro_f1']),viewer._rate(m['new_all_pr_micro']['f1']),
            viewer._rate(m['historical_all_pr_micro']['f1']),str(m['new_failed_groups']),str(m['historical_failed_groups'])]))
    return ('<p>与启动时冻结的testcase-002首批30 PR报告作描述性对照，仅统计base／索引／标签身份对齐的任务。历史预算与精确模型修订未完全统一，不自动排名。</p>'
            +ui.table(['方法','对齐PR数','本轮macro F1','历史macro F1','本轮全PR micro F1','历史全PR micro F1','本轮失败','历史失败'],rows))


def round_page(viewer,ui,bench,entry):
    doc=snapshot(bench,entry)
    content='<h1>'+esc(entry['name'])+'</h1>'+summary(viewer,ui,doc)
    content+='<details class="panel"><summary>启动时冻结的历史对照</summary>'+comparison(viewer,ui,doc)+'</details>'
    content+='<details class="panel"><summary>运行协议</summary><p>'+esc(protocol_description(doc))+'</p></details>'
    page=ui.page(viewer,entry['name'],[('overview','概览',content),('prs','PR 列表',pr_table(viewer,ui,doc,entry))])
    return page.replace('</body>',live_script(entry,doc)+'</body>',1)


def pr_page(viewer,ui,bench,entry,pr):
    doc=snapshot(bench,entry);task=next((t for t in doc['tasks'] if t['pr']==pr),None)
    if task is None:raise DisplayError('PR不属于本轮')
    panes=[]
    for method in doc['methods']:
        group=next(g for g in doc['groups'] if g['pr']==pr and g['method']==method)
        content=f'<h1>PR{pr} · {esc(task["title"])}</h1><p><a href="/round/{entry["id"]}#prs">← 本轮PR列表</a></p><h2>{esc(METHODS[method])} · {esc(group_label(group,doc))}</h2>'
        if independent_tests(doc):
            content+='<p class="pill">'+esc(protocol_description(doc))+'</p>'
        rows=[]
        for stage,label in [('production','生产定位'),('tests','测试更新判断')]:
            s=group['stages'][stage];u=s.get('usage') or {}
            status=STATES[s['status']]
            if s['status']=='RUNNING' and (doc['stale'] or doc['controller_state']=='STOPPED'):status='中断／进程状态待核查'
            rows.append(ui.cells([label,esc(status),esc(u.get('rollout_tokens') if u.get('status')=='RECORDED' else '未知／未返回'),esc(s.get('error') or '')]))
        content+=ui.table(['阶段','状态','rollout','失败原因'],rows)
        if group.get('skip_reason'):content+='<p>'+esc(group['skip_reason'])+'</p>'
        prod=group.get('production_predictions')
        if prod is not None:
            rows=[]
            for key,label in [('files','文件'),('classes','类'),('functions','函数')]:
                for c in prod[key]:rows.append(ui.cells([label,esc(c['path']),esc(c.get('symbol','')),esc(c['reason'])]))
            label='第一轮生产候选（人工分析材料）' if independent_tests(doc) else '第一轮生产候选'
            empty='成功空预测；此材料不影响第二轮全量测试搜索。' if independent_tests(doc) else '成功空预测：第二轮按PR描述直接定位测试。'
            content+='<h3>'+label+'</h3>'+(ui.table(['粒度','文件','符号','依据'],rows) if rows else '<p>'+empty+'</p>')
        tests=group.get('test_predictions')
        if tests is not None:
            rows=[]
            for c in tests['candidates']:
                decision='需要更新' if c['needs_update'] is True else '无需更新' if c['needs_update'] is False else '证据不足'
                rows.append(ui.cells([esc(c['path']),esc(', '.join(c['symbols'])),decision,esc(c.get('update_reason') or '未提供（允许）'),esc(c['relation_reason'])]))
            label='第二轮全量测试更新判断' if independent_tests(doc) else '第二轮测试候选与判断'
            relation='PR与测试依据' if independent_tests(doc) else '关联依据'
            content+='<h3>'+label+'</h3>'+(ui.table(['文件','源码testcase','判断','更新理由（可选）',relation],rows) if rows else '<p>成功空测试预测。</p>')
        metric=next((r for r in doc['evaluation_rows'] if r['pr']==pr and r['method']==method),None)
        if metric:
            a=metric['testcase'];content+='<h3>最终testcase评分</h3>'+ui.table(['TP','FP','FN','Precision','Recall','F1'],[ui.cells([str(a[k]) for k in ('tp','fp','fn')]+[viewer._rate(a[k]) for k in ('precision','recall','f1')])])
        else:content+='<p class="muted">未评分；定位预测不等于评价结果。</p>'
        panes.append((method,METHODS[method],content))
    return ui.page(viewer,f'PR{pr} 两阶段定位',panes).replace('</body>',live_script(entry,doc)+'</body>',1)
