"""P2 development comparison: unchanged public queries, sealed output, host scoring."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

from . import maintenance_view as view
from . import reader, search_view as search
from .p1_offline import complete_items, lookup_cost, RUN
from .p2_gate import OUTPUT, P1

VARIANTS = ('P', 'N', 'A', 'C')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def plan():
    if (OUTPUT/'query-seal.json').exists():
        raise ValueError('Queries already frozen')
    shutil.copyfile(P1/'queries.json', OUTPUT/'queries.json')
    files = [Path(__file__), Path(reader.__file__), Path(search.__file__), Path(view.__file__),
             Path(__file__).with_name('maintenance_static.py'), Path(__file__).with_name('p2_bundle.py')]
    write(OUTPUT/'query-seal.json', {'queries_sha256': search.sha(OUTPUT/'queries.json'),
          'p1_queries_sha256': search.sha(P1/'queries.json'), 'code': {str(p):search.sha(p) for p in files},
          'variants': list(VARIANTS), 'max_bytes':6000,'limit':25,
          'development_labels_previously_seen':True, 'new_field_weight':1})


def ablate(documents, categories):
    allowed = {*search.FIELDS, *('maintenance.'+c for c in categories)}
    docs=[]
    for doc in documents:
        fields=[f for f in doc['fields'] if f['field'] in allowed]
        docs.append(dict(doc, fields=fields, vectors=search.vectorize(fields)))
    stats=search.statistics(docs)
    for category in categories:
        field='maintenance.'+category
        stats['avg'][field]=sum(sum(d['vectors'].get(field,{}).values()) for d in docs)/max(1,len(docs))
    return docs,stats


def rank():
    if (OUTPUT/'rankings-seal.json').exists():
        raise ValueError('Rankings already frozen')
    seal=json.loads((OUTPUT/'query-seal.json').read_text())
    if search.sha(OUTPUT/'queries.json')!=seal['queries_sha256']:
        raise ValueError('Public queries changed')
    for name,digest in seal['code'].items():
        if search.sha(name)!=digest:
            raise ValueError('Code changed after query freeze: '+name)
    tasks=json.loads((OUTPUT/'queries.json').read_text())['tasks']
    by_base={}
    for task in tasks:
        by_base.setdefault(task['base_sha'],[]).append(task)
    files,checks,bundles={},[],{}
    for base,group in sorted(by_base.items()):
        root=OUTPUT/'representations'/base
        manifest=json.loads((root/'manifest.json').read_text())
        for name,digest in manifest['files'].items():
            if search.sha(root/name)!=digest:
                raise ValueError('Bundle changed')
        bundles[base]=search.sha(root/'manifest.json')
        documents,stats=search.load_index(root)
        variants={'N':(documents,stats), 'A':ablate(documents,['annotations']),
                  'C':ablate(documents,['inheritance','context_calls','imports','guards'])}
        with reader.connect(root) as db:
            cards={i:{'card':json.loads(c),'intention':json.loads(t)} for i,c,t in db.execute('SELECT id,card,intention FROM tests')}
            for task in group:
                check={'task_id':task['task_id'],'verified_hits':0,'pagination_units':0}
                # P is the actual frozen P1 R ranking/page, not a new implementation of the control.
                old=P1/'rankings'/task['task_id']
                prediction=json.loads((old/'R.json').read_text())
                control=dict(prediction,variant='P')
                first=prediction['ranked_ids'][0] if prediction['ranked_ids'] else None
                control['hit_lookup_cost']=None
                old_page=json.loads((old/'R.page.json').read_text())
                if first and old_page['items'] and old_page['items'][0].get('hit'):
                    control['hit_lookup_cost']=lookup_cost(search.lookup(db,first,old_page['items'][0]['hit']['ref']),reader.page)
                location=Path('rankings')/task['task_id']/'P.json'
                write(OUTPUT/location,control)
                shutil.copyfile(old/'R.page.json',(OUTPUT/location).with_suffix('.page.json'))
                for name in (location,location.with_suffix('.page.json')):
                    files[str(name)]=search.sha(OUTPUT/name)
                for variant,(docs,stat) in variants.items():
                    ranked=view.rank(docs,stat,task['queries'])
                    rows=[search.short_row(d,hits,score,cards[d['id']]) for d,hits,score in ranked]
                    binding=search.sha(root/'manifest.json')
                    page=search.search_page(rows,binding,0,25,6000,reader.page)
                    text=search.encoded(page)+'\n'
                    visible=complete_items(page)
                    if len(text.encode())>6000:
                        raise ValueError('Fixed output budget exceeded')
                    for row in visible:
                        if row['hit']:
                            h=row['hit']; evidence=view.lookup(root,db,row['id'],h['ref'])
                            if evidence['value'][h['start']:h['end']]!=h['text']:
                                raise ValueError('Unfaithful hit')
                            check['verified_hits']+=1
                    # Entire pagination must preserve the exact ordered units, independently of gold.
                    from .p1_offline import all_pieces
                    expected,got,offset=all_pieces(rows),[],0
                    while True:
                        part=search.search_page(rows,binding,offset,25,6000,reader.page)
                        got.extend(part['items'])
                        if part['next_cursor'] is None:
                            break
                        offset=search.cursor_offset(part['next_cursor'],binding)
                    if got!=expected:
                        raise ValueError('Pagination duplicates or omissions')
                    check['pagination_units']+=len(got)
                    first=ranked[0][0]['id'] if ranked else None
                    hit_lookup=None
                    if first and rows[0]['hit']:
                        hit_lookup=lookup_cost(view.lookup(root,db,first,rows[0]['hit']['ref']),reader.page)
                    location=Path('rankings')/task['task_id']/(variant+'.json')
                    write(OUTPUT/location,{'task_id':task['task_id'],'base_sha':base,'variant':variant,
                        'ranked_ids':[d['id'] for d,_,_ in ranked],'visible_ids':[r['id'] for r in visible],
                        'output_utf8_bytes':len(text.encode()),'returned_units':len(page['items']),
                        'visible_complete_tests':len(visible),
                        'first_result_lookup':lookup_cost(cards[first]['card'],reader.page) if first else None,
                        'hit_lookup_cost':hit_lookup})
                    (OUTPUT/location).with_suffix('.page.json').write_text(text)
                    for name in (location,location.with_suffix('.page.json')):
                        files[str(name)]=search.sha(OUTPUT/name)
                checks.append(check)
                print(json.dumps({'task_id':task['task_id'],'stage':'RANKINGS_SEALED'}),flush=True)
    write(OUTPUT/'offline-checks.json',checks)
    files['queries.json']=search.sha(OUTPUT/'queries.json')
    files['offline-checks.json']=search.sha(OUTPUT/'offline-checks.json')
    write(OUTPUT/'rankings-seal.json',{'files':files,'bundles':bundles,'query_seal_sha256':search.sha(OUTPUT/'query-seal.json'),
                                     'development_labels_previously_seen':True,'ranker_reads_labels':False})


def evaluate():
    if (OUTPUT/'offline-metrics.json').exists():
        raise ValueError('Metrics already exist')
    seal=json.loads((OUTPUT/'rankings-seal.json').read_text())
    for name,digest in seal['files'].items():
        if search.sha(OUTPUT/name)!=digest:
            raise ValueError('Sealed predictions changed')
    host=json.loads((RUN/'host-comparison/metrics.json').read_text())['tasks']
    tasks=json.loads((OUTPUT/'queries.json').read_text())['tasks'];rows=[]
    for task in tasks:
        gold=set(host[task['task_id']]['labels']['testcases'])
        inventory={e['id'] for e in host[task['task_id']]['index']['entries']}
        public=(task['title']+' '+task['body']).casefold()
        subgroup='type' if any(term in public for term in ('type','typing','annotation','check_untyped_defs')) else (
            'construction' if any(term in public for term in ('build_from_crawler','class','classes')) else 'other')
        for variant in VARIANTS:
            p=json.loads((OUTPUT/'rankings'/task['task_id']/(variant+'.json')).read_text())
            if not set(p['ranked_ids'])<=inventory or not gold<=inventory:
                raise ValueError('Source identity/denominator differs')
            hits=len(set(p['visible_ids'])&gold)
            first=next((i+1 for i,t in enumerate(p['visible_ids']) if t in gold),None)
            rows.append({'task_id':task['task_id'],'variant':variant,'subgroup':subgroup,'gold':len(gold),'hits':hits,
                'recall_at_6000B':hits/len(gold) if gold else None,'pool_hits':len(set(p['ranked_ids'])&gold),
                'pool_size':len(p['ranked_ids']),'first_target_visible_rank':first,'mrr_at_budget':1/first if first else 0,
                **{k:p[k] for k in ('visible_complete_tests','output_utf8_bytes','first_result_lookup','hit_lookup_cost')}})
    summaries={}
    for variant in VARIANTS:
        group=[r for r in rows if r['variant']==variant];positive=[r for r in group if r['gold']]
        count=sum(r['gold'] for r in positive)
        summaries[variant]={'tasks':len(group),'positive_tasks':len(positive),'gold':count,'hits':sum(r['hits'] for r in group),
            'macro_recall':sum(r['recall_at_6000B'] for r in positive)/len(positive),
            'micro_recall':sum(r['hits'] for r in group)/count,'pool_hits':sum(r['pool_hits'] for r in group),
            'macro_pool_recall':sum(r['pool_hits']/r['gold'] for r in positive)/len(positive),
            'hit_at_budget':sum(r['hits']>0 for r in positive)/len(positive),
            'mrr_at_budget':sum(r['mrr_at_budget'] for r in positive)/len(positive),
            'candidate_precision':sum(r['hits'] for r in group)/max(1,sum(r['visible_complete_tests'] for r in group)),
            'mean_visible_tests':sum(r['visible_complete_tests'] for r in group)/len(group),
            'no_positive':[r for r in group if not r['gold']]}
    paired={}
    for variant in ('N','A','C'):
        before={r['task_id']:r for r in rows if r['variant']=='P'};after={r['task_id']:r for r in rows if r['variant']==variant}
        paired[variant]={'improved':[i for i in before if after[i]['hits']>before[i]['hits']],
                         'regressed':[i for i in before if after[i]['hits']<before[i]['hits']],
                         'same':sum(after[i]['hits']==before[i]['hits'] for i in before)}
    write(OUTPUT/'offline-metrics.json',{'scope':'30 development PR; 6000 UTF-8 bytes per first page; not SDD predictions',
        'summaries':summaries,'rows':rows,'paired':paired,'rankings_seal_sha256':search.sha(OUTPUT/'rankings-seal.json')})
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','rank','evaluate'))
    args=parser.parse_args();{'plan':plan,'rank':rank,'evaluate':evaluate}[args.stage]()
