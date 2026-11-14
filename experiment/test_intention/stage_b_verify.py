"""TI-20 public-base provenance and actual bundle reader acceptance; no models."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tokenize

from .stage_b_bundle import OUTPUT, PARENT, BASELINES, checked, write
from . import reader, sensitivity_view as sensitivity, search_view as search
from .p1_offline import complete_items


def cli(root, repository, argv, cap=6000):
    # Repository path is passed by loading root in a tiny local adapter, without changing bundles.
    # Public deployed default is bundle parent=/workspace; host siblings differ.
    adapter='import sys; sys.path.insert(0,sys.argv[1]); import read; sys.exit(read.main(sys.argv[3:], root=sys.argv[1], repository=sys.argv[2]))'
    process=subprocess.run([sys.executable,'-B','-c',adapter,str(root),str(repository),*argv,'--max-bytes',str(cap),
                            '--limit','25'],capture_output=True,text=True)
    if process.returncode:raise ValueError(process.stdout+process.stderr)
    if len(process.stdout.encode())>cap:raise ValueError('Reader exceeded cap')
    return json.loads(process.stdout)


def main():
    if (OUTPUT/'source-verification.json').exists():raise ValueError('Verification already exists')
    all_rows=[];examples=[];kinds=Counter();total=Counter()
    for root in sorted((OUTPUT/'representations').iterdir()):
        manifest=checked(root);parent=checked(PARENT/root.name);repository=BASELINES/root.name/'repository'
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdd-bench/scrapy-sdd'))
        from batch.test_intention import verify_bundle
        verify_bundle(root/'manifest.json',root.name)
        files={};seen={};counts=Counter()
        for relative,digest in manifest['source_files'].items():
            path=repository/relative
            if search.sha(path)!=digest:raise ValueError('Base source changed')
            with tokenize.open(path) as stream:files[relative]=stream.read().splitlines()
        for name in ('.evidence.sqlite3','.maintenance.sqlite3','.search.sqlite3','index.json','relations.json'):
            if search.sha(root/name)!=parent['files'][name]:raise ValueError('A data changed')
        with reader.connect(root) as db:
            identities=[i for i, in db.execute('SELECT id FROM tests ORDER BY id')]
            for identity in identities:
                points,coverage=sensitivity.points(root,db,identity)
                for point in points:
                    location=point['source'];path=location['path'];start,end=location['start_line'],location['end_line']
                    if (path not in files or manifest['source_files'][path]!=location['file_sha256'] or
                        not 1<=start<=end<=len(files[path])):raise ValueError('Bad source sensitivity location')
                    counts[point['kind']]+=1
                    seen.setdefault(point['kind'],(identity,point))
            for kind,(identity,point) in sorted(seen.items()):
                for cap in (6000,12000):
                    # All continuation pieces must restore the expanded original point exactly.
                    items=[];offset=0
                    while True:
                        part=cli(root,repository,['point',identity,'--ref',point['ref'],'--offset',str(offset)],cap)
                        items+=part['items'];total['reader_calls']+=1
                        if part['next_offset'] is None:break
                        if part['next_offset']<=offset:raise ValueError('Pager made no progress')
                        offset=part['next_offset']
                    restored=complete_items({'items':items})
                    expected=sensitivity.expand(root,db,identity,point['ref'],repository)
                    if restored!=expected:raise ValueError('Point expansion changed')
                    short=cli(root,repository,['sensitive',identity],cap);total['reader_calls']+=1
                    # Existing show path delegates to original A implementation byte-for-byte as parsed JSON.
                    original=reader.page([reader.load_test(db,identity)['card']],0,25,cap)
                    if cli(root,repository,['show',identity],cap)!=original:raise ValueError('Default card changed')
                    total['reader_calls']+=1
                examples.append({'base_sha':root.name,'id':identity,'kind':kind,'short':sensitivity.short(point),
                                 'expanded':expected[0]})
        row={'base_sha':root.name,'tests':len(identities),'source_files':len(files),
             'sensitive_points':sum(counts.values()),'kinds':counts,'status':'PASS'}
        all_rows.append(row);kinds.update(counts)
        print(json.dumps(row),flush=True)
    write(OUTPUT/'source-examples.json',examples)
    write(OUTPUT/'source-verification.json',{'status':'PASS','bases':all_rows,'kinds':kinds,
        'tests':sum(r['tests'] for r in all_rows),'source_points':sum(kinds.values()),**total,
        'new_extraction':False,'all_saved_point_locations_checked':True,
        'multiline_direct_expression_extent':'unknown; start-line provenance only',
        'default_cards_and_search_index_unchanged_from_A':True})


if __name__=='__main__':main()
