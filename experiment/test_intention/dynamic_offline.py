"""Verify frozen D against C and original per-instance graphs without labels/models."""
import argparse
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from . import dynamic_view, reader
from .stage_b_bundle import checked, write
from test_trace.common import file_hash, read_json


def independent_depths(document):
    distances = {}
    for item in document['instances']:
        execution = item['execution_id']; adjacency = defaultdict(set)
        for edge in document['edges']:
            if execution in edge['supporting_instances']:
                adjacency[edge['caller']].add(edge['callee'])
        current = {document['source_test_id']: 0}; pending = deque(current)
        while pending:
            parent = pending.popleft()
            for child in adjacency[parent]:
                if child not in current:
                    current[child] = current[parent]+1; pending.append(child)
        for function, depth in current.items():
            distances[function] = min(depth, distances.get(function, depth))
    return distances


def cli(bundle, argv):
    process = subprocess.run([sys.executable, str(bundle/'read.py'), *argv], capture_output=True, text=True, check=False)
    if process.returncode or len(process.stdout.encode()) > 12000:
        raise ValueError('CLI_FAILED_OR_UNBOUNDED: '+process.stderr+process.stdout[:300])
    return json.loads(process.stdout)


def check_base(c, d, trace_root):
    original, manifest = checked(c), checked(d)
    if manifest['c_parent_manifest_sha256'] != file_hash(c/'manifest.json'):
        raise ValueError('C_PARENT_MANIFEST_CHANGED')
    preserved = {p:h for p,h in original['files'].items() if p not in {'read.py','README.md','.rgignore'}}
    if any(file_hash(d/p) != h for p,h in preserved.items()):
        raise ValueError('C_CONTENT_OR_SEARCH_CHANGED')
    if file_hash(d/'ti_read.py') != file_hash(c/'read.py'):
        raise ValueError('C_READER_NOT_PRESERVED')
    for name, target in [('dynamic_reader.py','read.py'),('dynamic_view.py','dynamic_view.py')]:
        if file_hash(d/target) != file_hash(Path(__file__).with_name(name)):
            raise ValueError('READER_CODE_DIFFERS_FROM_REVIEWED_SOURCE')
    trace_manifest = read_json(trace_root/'manifest.json')
    if manifest['trace_manifest_sha256'] != file_hash(trace_root/'manifest.json'):
        raise ValueError('TRACE_MANIFEST_CHANGED')
    index=read_json(trace_root/'index.json'); trace_entries={e['id']:e for e in index['tests']}
    checked_paths=memberships=complete=0; frequencies=Counter(); graphs=set(); statuses=Counter()
    independent_shallow={}; examples=[]
    with dynamic_view.connect(d) as db, reader.connect(c) as evidence:
        ids=[i for i, in evidence.execute('SELECT id FROM tests ORDER BY id')]
        methods=db.execute('SELECT id,status,expected,valid,production_count,shallow_count,graph FROM methods ORDER BY id').fetchall()
        if ids != [m[0] for m in methods]:raise ValueError('TI_INVENTORY_CHANGED')
        for identity,status,expected,valid,count,shallow,graph in methods:
            statuses[status]+=1
            source_entry=trace_entries.get(identity)
            if status != (source_entry['coverage_status'] if source_entry else 'not_discovered'):
                raise ValueError('SOURCE_TRACE_STATUS_CHANGED')
            rows=db.execute('SELECT function,depth,path FROM coverage WHERE test_id=? ORDER BY function',(identity,)).fetchall()
            if status != 'complete':
                if rows or graph is not None or count is not None or shallow is not None:
                    raise ValueError('INCOMPLETE_RUNTIME_DATA_EXPOSED')
                continue
            complete+=1;graphs.add(graph);document=read_json(d/graph)
            if file_hash(d/graph) != trace_manifest['files'][source_entry['path']]:
                raise ValueError('GRAPH_CHANGED_FROM_ORIGINAL_TRACE')
            if valid != expected or len(document['instances']) != expected or any(
                    i['evidence_status'] != 'valid' or i['outcome'] != 'passed' for i in document['instances']):
                raise ValueError('INCOMPLETE_INSTANCE_SET')
            production=set(document['production_covered_functions']); depths=independent_depths(document)
            if {r[0] for r in rows} != production or count != len(production):
                raise ValueError('COVERAGE_CHANGED')
            frequencies.update(production);memberships+=len(rows)
            independent_shallow[identity]={f for f in production if f in depths and depths[f]<=2}
            if shallow != len(independent_shallow[identity]):raise ValueError('SHALLOW_COUNT_DIFFERS')
            supports={(e['caller'],e['callee'],i) for e in document['edges'] for i in e['supporting_instances']}
            valid_ids={i['execution_id'] for i in document['instances']}
            for function,depth,path_text in rows:
                if depth != depths.get(function):raise ValueError('INDEPENDENT_DEPTH_DIFFERS')
                if path_text is None:
                    if depth is not None:raise ValueError('MISSING_PATH')
                    continue
                path=json.loads(path_text);nodes=path['nodes'];instance=path['execution_id']
                if (instance not in valid_ids or nodes[0]!=identity or nodes[-1]!=function or len(nodes)-1!=depth
                        or any((a,b,instance) not in supports for a,b in zip(nodes,nodes[1:]))):
                    raise ValueError('UNOBSERVED_OR_SPLICED_PATH')
                checked_paths+=1
        if dict(db.execute('SELECT function,tests FROM frequencies')) != dict(frequencies):
            raise ValueError('FUNCTION_FREQUENCY_DIFFERS')
        if {p.relative_to(d).as_posix() for p in (d/'dynamic').glob('*.json')} != graphs:
            raise ValueError('EXTRA_OR_MISSING_RUNTIME_PAYLOAD')
        seed=next((i for i,s in sorted(independent_shallow.items()) if s),None)
        shared_seed=next((i for i,s in sorted(independent_shallow.items()) if any(s&t for j,t in independent_shallow.items() if j!=i)),seed)
        # Exact independent neighbor set check on three deterministic source methods per base.
        probes=list(dict.fromkeys([i for i in [shared_seed,seed,*sorted(independent_shallow)[-1:]] if i]))
        for identity in probes:
            actual=dynamic_view.shared_rows(db,evidence,identity)
            expected={i for i,s in independent_shallow.items() if i!=identity and s&independent_shallow[identity]}
            if {r['id'] for r in actual}!=expected:raise ValueError('INDEPENDENT_NEIGHBORS_DIFFER')
            order=[]
            for row in actual:
                intersection=independent_shallow[identity]&independent_shallow[row['id']]
                minimum=min(frequencies[f] for f in intersection)
                if row['shared_function_count']!=len(intersection) or row['lowest_covering_test_count']!=minimum:
                    raise ValueError('SHARED_COUNT_OR_SORT_DIFFERS')
                order.append((minimum,-len(intersection),row['id']))
            if order!=sorted(order):raise ValueError('NEIGHBOR_SORT_DIFFERS')
        for query in ['timeout','request']:
            a,b=cli(c,['search','--query',query,'--limit','2']),cli(d,['search','--query',query,'--limit','2'])
            # Cursors bind to each publication; result content/rank/count must be identical.
            if {k:v for k,v in a.items() if k!='next_cursor'}!={k:v for k,v in b.items() if k!='next_cursor'}:
                raise ValueError('SEARCH_BEHAVIOR_CHANGED')
        if seed:
            for argv in [['show',seed],['coverage',seed],['trace',seed],['shared',shared_seed]]:
                examples.append({'command':argv,'result':cli(d,argv)})
    checked(d)  # Reading must not alter the sealed inventory/bytes.
    return {'base_sha':manifest['base_sha'],'status':'PASS','tests':len(ids),'statuses':dict(statuses),
            'complete_graphs':complete,'coverage_memberships':memberships,'validated_paths':checked_paths,
            'independent_neighbor_probes':len(probes),'search_queries_checked':2,
            'manifest_sha256':file_hash(d/'manifest.json'),'examples':examples}


def run(publication,c_materials,trace_artifacts,benchmark):
    material=read_json(publication/'materials.json');artifacts=read_json(trace_artifacts)['artifacts']
    out=publication/'offline';out.mkdir(exist_ok=False);rows=[]
    sys.path.insert(0,str(benchmark))
    from batch.test_intention import verify_bundle
    from batch.scaffold import METHODS
    from batch.stages import detect_prompt,matched_material_prompt
    for entry in material['bases']:
        base=entry['base_sha'];d=publication/'materials/D'/base
        if file_hash(d/'manifest.json')!=entry['manifest_sha256']:raise ValueError('D_PUBLICATION_CHANGED')
        row=check_base(c_materials/base,d,Path(artifacts[base]['path']).parent)
        write(out/(base+'-examples.json'),row.pop('examples'))
        rows.append(row);write(out/'progress.json',{'bases':rows,'completed':len(rows),'total':len(material['bases'])})
        print('D_OFFLINE_PASS '+str(len(rows))+'/'+str(len(material['bases']))+' '+base,flush=True)
    # Exercise the shared mounting/verifier contract for all three methods, no Docker/model.
    base=rows[0]['base_sha'];source=publication/'materials/D'/base;mounts=[]
    for method in METHODS:
        mount=out/'mount-check'/method/'test-intentions';shutil.copytree(source,mount)
        verify_bundle(mount/'manifest.json',base)
        prompt=detect_prompt(method,'testcase-v1')+matched_material_prompt('D')
        if 'shared TEST_ID' not in prompt:raise ValueError('D_PROMPT_NOT_INTEGRATED')
        write(out/(method+'-prompt.json'),{'method':method,'prompt':prompt})
        example=read_json(out/(base+'-examples.json'))[0]
        cli(mount,example['command'])
        if file_hash(mount/'manifest.json')!=file_hash(source/'manifest.json'):raise ValueError('METHOD_MATERIALS_DIFFER')
        mounts.append({'method':method,'manifest_sha256':file_hash(mount/'manifest.json'),'status':'PASS'})
    statuses=Counter()
    for row in rows:statuses.update(row['statuses'])
    result={'status':'PASS','group':'D','prs':material['prs'],'bases':len(rows),'methods':mounts,
            'tests_across_bases':sum(r['tests'] for r in rows),'statuses':dict(statuses),
            'validated_paths':sum(r['validated_paths'] for r in rows),
            'coverage_memberships':sum(r['coverage_memberships'] for r in rows),
            'independent_neighbor_probes':sum(r['independent_neighbor_probes'] for r in rows),
            'source_C_and_search_unchanged':True,'new_models':0,'new_test_executions':0,'bases_results':rows}
    write(publication/'offline-acceptance.json',result)
    lines=['# D 组：C＋完整动态轨迹与两层共享','',
           f"离线验证 PASS：{result['prs']} PR、{result['bases']} base、三种 SDD。未启动模型、Docker 或测试重新采集。",'',
           f"跨 base 累计测试方法记录 {result['tests_across_bases']}，状态 {dict(statuses)}。同一方法跨版本重复计数。",'',
           f"核验 {result['validated_paths']} 条可达路径、{result['coverage_memberships']} 条覆盖归属；独立复算 {result['independent_neighbor_probes']} 个测试的完整两层邻居集合。",'',
           '原 C 语义、静态证据和搜索索引字节保持不变。动态完整图按方法保存，路径逐实例证明；partial/unavailable/not_discovered 只提供状态，不携带动态集合或图。', '',
           '运行入口：materials/D/BASE/read.py。show 增加动态摘要；coverage/trace/shared 提供分页读取；trace --depth 0 为完整图，shared --with OTHER 展开全部共享证明。旧 neighbors 仍为静态关系。','',
           '首批仅材料构建和离线验收。之后的同环境 C/D 模型对照尚未启动，规模与预算另行确认。', '',
           '逐 base 的真实卡片、覆盖、图和共享查询见 offline/BASE-examples.json；三 SDD 提示和挂载校验见 offline/。']
    (publication/'REPORT.md').write_text('\n'.join(lines)+'\n')
    write(publication/'completion.json',{'status':'OFFLINE_VERIFIED','group':'D','prs':material['prs'],
                                        'bases':len(rows),'model_runs_started':0,
                                        'acceptance_sha256':file_hash(publication/'offline-acceptance.json')})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication',type=Path,required=True)
    parser.add_argument('--c-materials',type=Path,required=True)
    parser.add_argument('--trace-artifacts',type=Path,required=True)
    parser.add_argument('--benchmark',type=Path,required=True)
    args=parser.parse_args();run(args.publication.resolve(),args.c_materials.resolve(),args.trace_artifacts.resolve(),args.benchmark.resolve())


if __name__=='__main__':main()
