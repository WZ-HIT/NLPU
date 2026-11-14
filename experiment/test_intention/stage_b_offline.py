"""TI-23 host-only development replay; plan -> rank/seal -> evaluate.

No model execution. Fixed public queries and recovered historical literal queries
remain separate. No labels enter query extraction, ranking or bundle export.
"""
import argparse
from collections import Counter, defaultdict
import csv
import io
import json
from pathlib import Path
import shlex

from . import reader, maintenance_view as view, search_view as search
from .stage_b_bundle import OUTPUT, PARENT, checked, write
from .p1_offline import complete_items, all_pieces, lookup_cost

ROOT=OUTPUT.parent
OLD=ROOT/'p2-20261103-v1/representations'
HISTORY=ROOT/'p2-first30-v1'
PUBLIC_QUERIES=ROOT/'p1-20261103-v2/queries.json'
VARIANTS=('OLD','NEW')
LIMIT, MAX_BYTES=25,6000


def tokens(command):
    """Unwrap shell -c without executing shell text. Complex commands are not guessed."""
    try:
        words=shlex.split(command)
        if len(words)>=3 and Path(words[0]).name in ('bash','sh') and words[1] in ('-c','-lc'):
            return tokens(words[2])
        lexer=shlex.shlex(command,posix=True,punctuation_chars=';&|()<>')
        lexer.whitespace_split=True
        return list(lexer)
    except ValueError:
        return []


def searches(command):
    words=tokens(command); results=[]; rejected=[]
    for i, word in enumerate(words[:-1]):
        if Path(word).name!='read.py' or words[i+1]!='search':
            continue
        args=[]
        for token in words[i+2:]:
            if token and all(c in ';&|()<>' for c in token):break
            args.append(token)
        query={'queries':[],'mode':'or','sort':'field-bm25-v1','selected':[],'file':None}
        j=0; error=None
        while j<len(args):
            key=args[j]; j+=1
            if '=' in key:
                key,value=key.split('=',1)
            elif j<len(args):
                value=args[j]; j+=1
            else:
                error='MISSING_ARGUMENT';break
            if '$' in value or '`' in value or not value:
                error='DYNAMIC_OR_EMPTY_ARGUMENT';break
            if key=='--query':query['queries'].append(value)
            elif key=='--mode':query['mode']=value
            elif key=='--sort':query['sort']=value
            elif key=='--search-field':query['selected'].append(value)
            elif key=='--file':query['file']=value
            elif key in ('--limit','--max-bytes','--cursor','--offset'):
                pass  # Canonical replay starts at first page with the common fixed budget.
            else:
                error='UNSUPPORTED_ARGUMENT:'+key;break
        if not query['queries'] or query['mode'] not in ('or','and') or query['sort'] not in search.SORTS:
            error=error or 'UNSUPPORTED_QUERY_OPTIONS'
        if any(f not in (*search.FIELDS,*view.EXTRA_FIELDS) for f in query['selected']):
            error='UNSUPPORTED_SEARCH_FIELD'
        if error:rejected.append({'reason':error,'tokens':args})
        else:results.append(query)
    return results,rejected


def plan(output=OUTPUT):
    if (output/'replay-plan.json').exists():raise ValueError('Replay already planned')
    fixed=json.loads(PUBLIC_QUERIES.read_text())
    tasks={t['task_id']:t for t in fixed['tasks']}
    rows=[]
    for task in tasks.values():
        rows.append({'key':'fixed-'+task['task_id'],'kind':'fixed_public','task_id':task['task_id'],
                     'base_sha':task['base_sha'],'queries':task['queries'],'mode':'or',
                     'sort':'field-bm25-v1','selected':[],'file':None,'sources':[]})
    traces=[];rejected=[];actual={}
    run=next((HISTORY/'execution-root/sdd-bench/scrapy-sdd/batch/runs').glob('round-*'))
    for path in sorted((run/'tasks').glob('*/runs/*/detect/executions/*/attempt-*/agent.jsonl')):
        parts=path.relative_to(run/'tasks').parts;task,method=parts[0],parts[2]
        if task not in tasks:continue
        traces.append({'path':str(path),'sha256':search.sha(path),'task_id':task,'method':method})
        for line, raw in enumerate(path.read_text().splitlines(),1):
            event=json.loads(raw);item=event.get('item',{})
            if event.get('type')!='item.completed' or item.get('type')!='command_execution':continue
            queries,failures=searches(item.get('command',''))
            source={'trace':str(path),'line':line,'exit_code':item.get('exit_code')}
            rejected.extend(dict(f,source=source) for f in failures)
            for query in queries:
                # Recover attempted queries, including failed historical calls; success is disclosed.
                key=search.encoded([task,method,query])
                if key not in actual:
                    actual[key]=dict(query,kind='historical_actual',task_id=task,method=method,
                                     base_sha=tasks[task]['base_sha'],sources=[])
                actual[key]['sources'].append(source)
    import hashlib
    for key,row in sorted(actual.items()):
        rows.append(dict(row,key='actual-'+hashlib.sha256(key.encode()).hexdigest()[:24]))
    write(output/'queries-fixed.json',fixed)
    write(output/'replay-plan.json',{'version':'ti23-replay-v1','queries':rows,'traces':traces,
        'unrecovered':rejected,'budget':{'max_bytes':MAX_BYTES,'limit':LIMIT},
        'historical_parser':'literal read.py search commands only; unsupported/dynamic cases remain unknown',
        'development_labels_previously_seen':True,'new_labels_read':False,
        'fixed_public_source_sha256':search.sha(PUBLIC_QUERIES)})
    code=[Path(__file__),Path(reader.__file__),Path(view.__file__),Path(search.__file__)]
    write(output/'replay-plan-seal.json',{'plan_sha256':search.sha(output/'replay-plan.json'),
          'code':{str(p):search.sha(p) for p in code}})
    print(json.dumps({'queries':len(rows),'fixed':30,'actual':len(actual),'traces':len(traces),
                      'unrecovered_calls':len(rejected)}))


def rank(output=OUTPUT):
    if (output/'rankings-seal.json').exists():raise ValueError('Rankings already sealed')
    seal=json.loads((output/'replay-plan-seal.json').read_text())
    if search.sha(output/'replay-plan.json')!=seal['plan_sha256']:raise ValueError('Plan changed')
    for path,digest in seal['code'].items():
        if search.sha(path)!=digest:raise ValueError('Code changed after plan freeze')
    plan=json.loads((output/'replay-plan.json').read_text());groups=defaultdict(list)
    for query in plan['queries']:groups[query['base_sha']].append(query)
    files={};bundles={};counts=Counter()
    for base,queries in sorted(groups.items()):
        for variant,parent in (('OLD',OLD),('NEW',output/'representations')):
            root=parent/base;checked(root);bundles[f'{variant}/{base}']=search.sha(root/'manifest.json')
            docs,stats=search.load_index(root)
            with reader.connect(root) as db:
                cards={i:{'card':json.loads(c),'intention':json.loads(t)}
                       for i,c,t in db.execute('SELECT id,card,intention FROM tests')}
                for query in queries:
                    ranked=view.rank(docs,stats,query['queries'],mode=query['mode'],sort=query['sort'],
                                     selected=query['selected'],file=query['file'])
                    rows=[search.short_row(d,h,s,cards[d['id']]) for d,h,s in ranked]
                    binding=bundles[f'{variant}/{base}'];first=None;visible=[];got=[];offset=0;calls=0;byte_count=0
                    while True:
                        part=search.search_page(rows,binding,offset,LIMIT,MAX_BYTES,reader.page)
                        size=len((search.encoded(part)+'\n').encode())
                        if size>MAX_BYTES:raise ValueError('Page byte limit exceeded')
                        calls+=1;byte_count+=size;got+=part['items'];visible+=complete_items(part)
                        if first is None:first=part
                        if part['next_cursor'] is None:break
                        offset=search.cursor_offset(part['next_cursor'],binding)
                    if got!=all_pieces(rows):raise ValueError('Pagination duplicated or omitted units')
                    # Every complete short row must retain an exact original hit excerpt.
                    for row in rows:
                        hit=row['hit']
                        if hit:
                            original=view.lookup(root,db,row['id'],hit['ref'])['value']
                            if original[hit['start']:hit['end']]!=hit['text']:raise ValueError('Unfaithful hit')
                            counts['hit_refs_checked']+=1
                    first_ids=[r['id'] for r in complete_items(first)]
                    # Fragmented rows assembled across pages are visible only after all pieces were returned.
                    continued=[r['id'] for r in complete_items({'items':got})]
                    if continued!=[r['id'] for r in rows]:raise ValueError('Complete continued result mismatch')
                    result={'key':query['key'],'task_id':query['task_id'],'kind':query['kind'],'variant':variant,
                        'ranked_ids':[d['id'] for d,h,s in ranked],'first_page_ids':first_ids,
                        'continued_ids':continued,'first_page_bytes':len((search.encoded(first)+'\n').encode()),
                        'all_pages_calls':calls,'all_pages_bytes':byte_count,
                        'first_show_cost':lookup_cost(cards[rows[0]['id']]['card'],reader.page) if rows else None,
                        'first_hit_cost':lookup_cost(view.lookup(root,db,rows[0]['id'],rows[0]['hit']['ref']),reader.page)
                                         if rows and rows[0]['hit'] else None}
                    relative=Path('rankings')/query['key']/(variant+'.json')
                    write(output/relative,result);files[str(relative)]=search.sha(output/relative)
                    if query['kind']=='fixed_public':
                        pagepath=relative.with_suffix('.page.json');write(output/pagepath,first);files[str(pagepath)]=search.sha(output/pagepath)
                    counts['replays']+=1;counts['page_units']+=len(got)
            print(json.dumps({'base':base,'variant':variant,'queries':len(queries),'stage':'RANKED'}),flush=True)
    write(output/'rankings-seal.json',{'files':files,'bundles':bundles,'checks':counts,
        'plan_seal_sha256':search.sha(output/'replay-plan-seal.json'),'ranker_reads_labels':False,
        'development_labels_previously_seen':True})


def evaluate(output=OUTPUT):
    if (output/'offline-metrics.json').exists():raise ValueError('Evaluation already exists')
    seal=json.loads((output/'rankings-seal.json').read_text())
    for name,digest in seal['files'].items():
        if search.sha(output/name)!=digest:raise ValueError('Sealed rankings changed')
    if search.sha(output/'replay-plan-seal.json')!=seal['plan_seal_sha256']:raise ValueError('Plan seal changed')
    plan=json.loads((output/'replay-plan.json').read_text())
    # Host-only labels are opened only after all query/ranking files have been sealed.
    hostpath=HISTORY/'host-comparison/metrics.json';host=json.loads(hostpath.read_text())
    tasks=host['tasks'];rows=[];diagnoses=[]
    for q in plan['queries']:
        gold=set(tasks[q['task_id']]['labels']['testcases'])
        for variant in VARIANTS:
            prediction=json.loads((output/'rankings'/q['key']/(variant+'.json')).read_text())
            pool=set(prediction['ranked_ids']);first=set(prediction['first_page_ids'])
            rows.append({'key':q['key'],'task_id':q['task_id'],'kind':q['kind'],'variant':variant,
                'gold':len(gold),'pool_hits':len(pool&gold),'first_hits':len(first&gold),
                'pool_count':len(pool),'first_count':len(first),
                'first_target_rank':next((i+1 for i,t in enumerate(prediction['ranked_ids']) if t in gold),None),
                **{k:prediction[k] for k in ('first_page_bytes','all_pages_calls','all_pages_bytes','first_show_cost','first_hit_cost')}})
        if q['kind']=='fixed_public':
            new=json.loads((output/'rankings'/q['key']/'NEW.json').read_text())
            root=output/'representations'/q['base_sha']
            with reader.connect(root) as db:
                status={i:json.loads(c)['status'] for i,c in db.execute('SELECT id,card FROM tests')}
            for identity in sorted(gold):
                diagnoses.append({'task_id':q['task_id'],'id':identity,'semantic_status':status[identity],
                    'fixed_query_stage':'MATCH_MISS' if identity not in new['ranked_ids'] else
                        'FIRST_PAGE_COMPLETE' if identity in new['first_page_ids'] else 'LATER_PAGE',
                    'fixed_query_rank':new['ranked_ids'].index(identity)+1 if identity in new['ranked_ids'] else None,
                    'actual_exposure':'UNKNOWN','decision':'UNKNOWN','cause':'NOT_ESTABLISHED'})
    summaries={}
    for kind in ('fixed_public','historical_actual'):
        for variant in VARIANTS:
            selected=[r for r in rows if r['kind']==kind and r['variant']==variant]
            positive=[r for r in selected if r['gold']]
            summaries[f'{kind}/{variant}']={'queries':len(selected),'positive_queries':len(positive),
                'macro_first_page_recall':sum(r['first_hits']/r['gold'] for r in positive)/len(positive) if positive else None,
                'micro_first_page_recall':sum(r['first_hits'] for r in positive)/sum(r['gold'] for r in positive) if positive else None,
                'macro_pool_recall':sum(r['pool_hits']/r['gold'] for r in positive)/len(positive) if positive else None,
                'mean_first_page_tests':sum(r['first_count'] for r in selected)/len(selected) if selected else None,
                'note':'Historical query averages weight queries, not independent PRs; diagnostic only' if kind=='historical_actual' else '30 fixed public PR queries; 29 positive tasks'}
    write(output/'offline-metrics.json',{'scope':'30 development PR, retrieval replay only; no new Detect predictions',
        'summaries':summaries,'rows':rows,'ranking_seal_sha256':search.sha(output/'rankings-seal.json'),
        'host_metrics_sha256':search.sha(hostpath),'new_decision_records':'not present in historical runs; UNKNOWN'})
    write(output/'target-stage-diagnosis.json',diagnoses)
    export_csv(output/'target-stage-diagnosis.csv',diagnoses)
    write(output/'historical-decision-diagnosis.json',historical_exposure(plan,host))
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


def export_csv(path,rows):
    if not rows:return
    with path.open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def historical_exposure(plan,host):
    """Conservative observed API outputs, never infer a decision from a keyword."""
    rows=[]
    for trace in plan['traces']:
        path=Path(trace['path'])
        if search.sha(path)!=trace['sha256']:raise ValueError('Historical trace changed')
        observed=defaultdict(lambda:{'name_only':[],'complete_result':[],'source_expanded':[]})
        inventory={e['id'] for e in host['tasks'][trace['task_id']]['index']['entries']}
        for line,raw in enumerate(path.read_text().splitlines(),1):
            event=json.loads(raw);item=event.get('item',{})
            if event.get('type')!='item.completed' or item.get('type')!='command_execution':continue
            text=item.get('aggregated_output','');command=item.get('command','')
            for identity in inventory:
                if identity in text:observed[identity]['name_only'].append(line)
            # Only a complete JSON output can establish a complete structured result.
            try:page=json.loads(text)
            except (ValueError,TypeError):continue
            if not isinstance(page,dict) or not isinstance(page.get('items'),list):continue
            for record in complete_items(page):
                identity=record.get('id')
                if identity in inventory:observed[identity]['complete_result'].append(line)
            words=tokens(command)
            for i,word in enumerate(words[:-2]):
                if Path(word).name=='read.py' and words[i+1]=='source' and words[i+2] in inventory:
                    # This proves returned source lines, not that the relevant condition was read.
                    if any(isinstance(r,dict) and isinstance(r.get('line'),int) and 'source' in r for r in page['items']):
                        observed[words[i+2]]['source_expanded'].append(line)
        measured=next(r for r in host['rows'] if r['task_id']==trace['task_id'] and r['method']==trace['method'])
        predicted=set(measured.get('prediction',{}).get('testcases',[]))
        gold=set(host['tasks'][trace['task_id']]['labels']['testcases'])
        for identity in sorted(gold|predicted|set(observed)):
            exposure=observed[identity]
            stage=next((s for s in ('source_expanded','complete_result','name_only') if exposure[s]),'UNKNOWN')
            rows.append({'task_id':trace['task_id'],'method':trace['method'],'id':identity,
                'is_gold':identity in gold,'selected_final':identity in predicted,'run_state':measured['state'],
                'observed_exposure':stage,'event_lines':exposure,'trace':str(path),'trace_sha256':trace['sha256'],
                'decision_state':'selected_final' if identity in predicted else 'UNKNOWN',
                'exclusion_reason':'UNKNOWN','method_edit_reason':'UNKNOWN',
                'limit':'Legacy run has no TI-21 record; source line return is not proof of key evidence read'})
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','rank','evaluate'))
    args=parser.parse_args()
    globals()[args.action]()


if __name__=='__main__':main()
