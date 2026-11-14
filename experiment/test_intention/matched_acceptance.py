"""TI-24/25: verify actual B/C databases, index statistics and public entrypoints."""
from collections import Counter
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import sys

from .matched_materials import OUTPUT,PARENT,STATIC,CODE,build_index
from .stage_b_bundle import checked,write
from . import reader,search_view as search,maintenance_view as maintenance


def verify_base(base,output=OUTPUT):
    left=output/'materials/B'/base;right=output/'materials/C'/base
    b,c=checked(left),checked(right);parent=checked(PARENT/base)
    raw=json.loads((STATIC/(base+'.json')).read_text());pure={t['id']:t for t in raw['tests']}
    if b['source_files']!=c['source_files'] or b['source_files']!=parent['source_files']:
        raise ValueError('Source inventories differ')
    if any(search.sha(left/n)!=search.sha(right/n) for n in (*CODE,'.maintenance.sqlite3')):
        raise ValueError('B/C code or maintenance facts differ')
    counts=Counter();cached={}
    with reader.connect(left) as db,reader.connect(right) as semantic,reader.connect(PARENT/base) as original:
        b_rows=db.execute('SELECT * FROM tests ORDER BY id').fetchall()
        c_rows=semantic.execute('SELECT * FROM tests ORDER BY id').fetchall()
        original_rows=original.execute('SELECT * FROM tests ORDER BY id').fetchall()
        if len(b_rows)!=len(c_rows) or len(b_rows)!=len(pure):raise ValueError('Identity count differs')
        for static_row,sem_row,old_row in zip(b_rows,c_rows,original_rows):
            identity,path,card,intention,facts,refs,uncertainty,location=static_row
            if (identity,path,facts,refs,location)!=(sem_row[0],sem_row[1],sem_row[4],sem_row[5],sem_row[7]):
                raise ValueError('B/C static values differ')
            if sem_row[:2]!=old_row[:2] or any(json.loads(sem_row[i])!=json.loads(old_row[i]) for i in range(2,8)):
                raise ValueError('C record differs from accepted B-stage semantic input')
            if json.loads(intention) is not None or json.loads(uncertainty)!=pure[identity]['uncertainty']:
                raise ValueError('Semantic record or mixed uncertainty leaked into B')
            card=json.loads(card)
            if set(card)!={'id','location','status','dependency_candidates','evidence','uncertainty_count'} or card['status']!='STATIC_ONLY':
                raise ValueError('Unexpected B card content')
            if json.loads(facts)!={k:v for k,v in pure[identity]['static'].items() if k!='dependency_links'}:
                raise ValueError('B facts differ from pure base record')
            if json.loads(sem_row[3]):counts['generated_C']+=1
            else:counts['fallback_C']+=1
        for table in ('contexts','edges'):
            if db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()!=semantic.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall():
                raise ValueError('Static navigation differs')
        if db.execute('SELECT * FROM files ORDER BY path').fetchall()!=semantic.execute('SELECT * FROM files ORDER BY path').fetchall():
            raise ValueError('File navigation differs')
        if any(json.loads(value).get('topic_samples') for value, in db.execute('SELECT metadata FROM files')):
            raise ValueError('Generated file topics leaked')
        if db.execute('PRAGMA freelist_count').fetchone()[0]!=0:raise ValueError('Unverified freed pages')
    # Independently rebuild each expected projection/vector/statistics in memory.
    for group,root in [('B',left),('C',right)]:
        with reader.connect(root) as db:
            saved,stats=search.load_index(root);expected=list(search.read_records(db))
        for doc,actual in zip(expected,saved):
            facts,_=maintenance.load(root,doc['id']);doc['fields']+=maintenance.fields(facts)
            doc['vectors']=search.vectorize(doc['fields'])
            if doc['id']!=actual['id'] or doc['fields']!=actual['fields'] or doc['vectors']!=actual['vectors']:
                raise ValueError('Index projection not derived from allowed group material')
            if group=='B' and any(f['field'].startswith('semantic.') for f in actual['fields']):
                raise ValueError('Semantic search field leaked')
            counts['verified_index_fields']+=len(actual['fields'])
        if len(saved)!=len(expected):raise ValueError('Index size differs')
        check=search.statistics(expected)
        for field in maintenance.EXTRA_FIELDS:
            check['avg'][field]=sum(sum(d['vectors'].get(field,{}).values()) for d in expected)/max(1,len(expected))
        if check!=stats:raise ValueError('Group-local index statistics differ')
        counts['tests_'+group]=len(expected)
    return {'base_sha':base,'status':'PASS',**counts,
            'B_manifest_sha256':search.sha(left/'manifest.json'),'C_manifest_sha256':search.sha(right/'manifest.json')}


def main():
    if (OUTPUT/'material-verification.json').exists():raise ValueError('Already verified')
    rows=[]
    for source in sorted(PARENT.iterdir()):
        row=verify_base(source.name);rows.append(row);print(json.dumps(row),flush=True)
    write(OUTPUT/'material-verification.json',{'status':'PASS','bases':rows,'new_model_calls':0,
        'B_semantics_removed_from_fresh_database':True,'group_local_statistics_verified':True,
        'C_matches_accepted_parent':True,'A_has_no_package':True})


if __name__=='__main__':main()
