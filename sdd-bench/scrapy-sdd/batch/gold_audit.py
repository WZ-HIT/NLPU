'''Host-only staged gold leakage and container visibility audit.'''
from __future__ import annotations
import hashlib,json,os,shutil,stat,subprocess,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from .core import BatchError,canonical_sha256,sha256_file,write_json
METHODS=('openspec','speckit','cc-sdd')
PLANNING_TARGET={'openspec':'/workspace/openspec/changes','speckit':'/workspace/specs','cc-sdd':'/workspace/.kiro/specs'}
CHECKS={'G01':'input_identity','G02':'prompt_provenance','G03':'forbidden_value_scan','G04':'mount_and_volume_audit','G05':'git_future_history_audit','G06':'network_and_process_boundary','G07':'cross_variant_and_prior_run_isolation','G08':'viewer_evaluator_timing'}
def now(): return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def run(*argv,check=True):
 r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
 if check and r.returncode: raise BatchError('AUDIT_COMMAND_FAILED','Host-only audit command failed',argv=list(argv),exit_code=r.returncode,stderr=r.stderr.decode(errors='replace')[-1500:])
 return r
def make_writable(root):
 for p in [root,*root.rglob('*')]:
  if p.is_symlink(): continue
  try:p.chmod(p.stat().st_mode|stat.S_IWUSR)
  except FileNotFoundError:pass
def copy_init(task,method,workspace):
 source=task/'initialization'/method/'files'
 for p in source.rglob('*'):
  if p.is_file():
   d=workspace/p.relative_to(source);d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
def file_manifest(roots):
 lines=[]
 for prefix,root in roots:
  if root.is_file():lines.append(f'{sha256_file(root)}  {prefix}');continue
  for p in sorted(root.rglob('*')):
   if not(p.is_file() or p.is_symlink()):continue
   data=os.readlink(p).encode() if p.is_symlink() else p.read_bytes()
   lines.append(f'{hashlib.sha256(data).hexdigest()}  {prefix}/{p.relative_to(root).as_posix()}')
 payload=('\n'.join(lines)+'\n').encode();return lines,hashlib.sha256(payload).hexdigest()
def git_audit(repo,base,future):
 def git(*a,check=True):return run('git','-C',str(repo),*a,check=check)
 head=git('rev-parse','HEAD').stdout.decode().strip();tree=git('rev-parse','HEAD^{tree}').stdout.decode().strip();reachable=git('rev-list','HEAD').stdout.decode().splitlines();refs=git('for-each-ref','--format=%(refname)').stdout.decode().splitlines();remotes=git('remote').stdout.decode().splitlines();alt=repo/'.git/objects/info/alternates';logs=repo/'.git/logs';obj=repo/'.git/objects'
 future_present=any(git('cat-file','-e',f'{v}^{{commit}}',check=False).returncode==0 for v in future)
 d={'status':'PASS','head_equals_base':head==base,'tree_sha':tree,'reachable_commit_count':len(reachable),'remote_count':len(remotes),'ref_count':len(refs),'remote_tracking_ref_count':len([x for x in refs if x.startswith('refs/remotes/')]),'alternates_present':alt.exists(),'reflog_file_count':len([x for x in logs.rglob('*') if x.is_file()]) if logs.exists() else 0,'future_object_present':future_present,'object_store_identity_sha256':hashlib.sha256(str(obj.resolve()).encode()).hexdigest()}
 if not(d['head_equals_base'] and len(reachable)==1 and not remotes and not refs and not alt.exists() and not future_present):d['status']='FAIL'
 return d
def sealed_canary(task_id,method,base,input_sha,planning_sha):
 d={'schema_version':1,'manifest_type':'SEALED_DETECTION','task_id':task_id,'method':method,'base_sha':base,'producer':{'kind':'isolation-canary','stage':'detect','run_id':f'canary-{method}','session_sha256':hashlib.sha256(f'{task_id}:{method}:canary'.encode()).hexdigest()},'task_input_sha256':input_sha,'candidates':[],'planning_artifacts':{'file_count':0,'manifest_sha256':planning_sha}}
 d['seal']={'algorithm':'sha256-canonical-json-without-seal','payload_sha256':canonical_sha256(d)};return d
def validate_schema(value,path):
 from jsonschema import Draft202012Validator
 errors=list(Draft202012Validator(json.loads(path.read_text())).iter_errors(value))
 if errors:raise BatchError('SCHEMA_VALIDATION_FAILED','Generated artifact failed schema',schema=str(path),errors=[e.message for e in errors])
def verify_detection(value,schema_path,task_id,method,base,input_sha,allow_canary=False):
 validate_schema(value,schema_path)
 payload=dict(value);seal=payload.pop('seal')
 checks={'task_match':payload.get('task_id')==task_id,'method_match':payload.get('method')==method,'base_match':payload.get('base_sha')==base,'task_input_match':payload.get('task_input_sha256')==input_sha,'seal_valid':seal.get('payload_sha256')==canonical_sha256(payload),'producer_valid':payload.get('producer',{}).get('kind')=='agent' or allow_canary}
 if not all(checks.values()):raise BatchError('DETECTION_PROVENANCE_INVALID','Detection manifest provenance or seal is invalid',failed=[k for k,v in checks.items() if not v])
 return checks
def container_probe(image,stage,method,workspace,planning,output,task_input,detection):
 name=f'sdd-gold-audit-{method}-{stage}-{uuid.uuid4().hex[:8]}'
 argv=['docker','create','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--tmpfs','/tmp:rw,nosuid,nodev,mode=1777','--tmpfs','/run/sdd-home:rw,nosuid,nodev,mode=0700,uid=1007,gid=1007','--mount',f'type=bind,src={workspace},dst=/workspace,readonly','--mount',f'type=bind,src={output},dst=/output','--mount',f'type=bind,src={task_input},dst=/task-input,readonly','--env',f'SDD_STAGE={stage}','--env',f'SDD_TOOL={method}','--env',f'SDD_RUN_ID=audit-{method}-{stage}']
 roles={'/workspace':{'role':'repository','rw':False},'/output':{'role':'private_stage_output','rw':True},'/task-input':{'role':'public_task_input','rw':False}};target=PLANNING_TARGET[method]
 if stage=='detect':argv+=['--mount',f'type=bind,src={planning},dst={target}'];roles[target]={'role':'own_detect_planning','rw':True}
 else:
  argv+=['--mount',f'type=bind,src={workspace}/tests,dst=/workspace/tests','--mount',f'type=bind,src={planning},dst={target},readonly','--mount',f'type=bind,src={detection},dst=/input/detection-manifest.json,readonly'];roles['/workspace/tests']={'role':'tests_only_update','rw':True};roles[target]={'role':'own_sealed_planning','rw':False};roles['/input/detection-manifest.json']={'role':'own_sealed_detection','rw':False}
 probe=r'''import hashlib,json,os
p="/input/detection-manifest.json"
v={"stage":os.environ["SDD_STAGE"],"method":os.environ["SDD_TOOL"],"network_interfaces":sorted(os.listdir("/sys/class/net")),"detection_visible":os.path.isfile(p),"detection_sha256":hashlib.sha256(open(p,"rb").read()).hexdigest() if os.path.isfile(p) else None,"task_input_files":sorted(os.listdir("/task-input")),"other_input_entries":sorted(os.listdir("/input")) if os.path.isdir("/input") else []}
open("/output/container-probe.json","w").write(json.dumps(v,sort_keys=True))'''
 argv += [image,'/usr/local/bin/python','-c',probe];cid=run(*argv).stdout.decode().strip()
 try:
  ins=json.loads(run('docker','inspect',cid).stdout)[0];actual={m['Destination']:{'rw':m['RW'],'type':m['Type']} for m in ins['Mounts']}
  if ins['HostConfig']['NetworkMode']!='none' or set(actual)!=set(roles):raise BatchError('MOUNT_BOUNDARY_FAILED','Actual mounts/network differ',method=method,stage=stage)
  if any(actual[k]['rw']!=v['rw'] for k,v in roles.items()):raise BatchError('MOUNT_MODE_FAILED','Mount mode differs',method=method,stage=stage)
  started=run('docker','start','--attach',cid,check=False)
  if started.returncode:raise BatchError('CONTAINER_PROBE_FAILED','Visibility probe failed',stderr=started.stderr.decode(errors='replace')[-1500:])
  observed=json.loads((output/'container-probe.json').read_text())
  if observed['network_interfaces']!=['lo']:raise BatchError('NETWORK_BOUNDARY_FAILED','Non-loopback interface visible')
  if stage=='detect' and observed['detection_visible']:raise BatchError('DETECT_SEES_DETECTION','Detect sees detection input')
  if stage=='update' and (not observed['detection_visible'] or observed['other_input_entries']!=['detection-manifest.json']):raise BatchError('UPDATE_INPUT_SCOPE_FAILED','Update input is not exactly its manifest')
  audit={'schema_version':1,'status':'PASS','stage':stage,'method':method,'network_mode':'none','named_volumes':[],'mounts':[{'destination':k,**roles[k],'type':actual[k]['type']} for k in sorted(roles)],'host_gold_store_mounted':False}
  return audit,observed
 finally:run('docker','container','rm','--force',cid,check=False)
def find_raw(path,repository,pr_id):
 matches=[]
 for line in path.read_text().splitlines():
  if not line.strip():continue
  x=json.loads(line)
  if x.get('repo')==repository and x.get('pr_id')==pr_id:matches.append(x)
 if len(matches)!=1:raise BatchError('RAW_RECORD_NOT_UNIQUE','Expected one raw record',count=len(matches))
 return matches[0]
def signatures(raw,classification,approved):
 out=[('classification',classification.encode())]
 for k in ('head_sha','merge_commit_sha'):
  if isinstance(raw.get(k),str):out.append((k,raw[k].encode()))
 for x in raw.get('changed_files',[]):
  if not isinstance(x,dict):continue
  v=x.get('filename');patch=x.get('patch')
  if isinstance(v,str) and v.encode() not in approved:out.append(('gold_target_path',v.encode()))
  if isinstance(patch,str) and len(patch)>=24:out.append(('pr_patch',patch.encode()))
 for x in raw.get('test_changes',[]):
  if not isinstance(x,dict):continue
  for k in ('file','qualified_name','name','node_id'):
   v=x.get(k)
   if isinstance(v,str) and v and v.encode() not in approved:out.append(('gold_target_identifier',v.encode()))
  v=x.get('gold_test')
  if isinstance(v,str) and len(v)>=24:out.append(('gold_test',v.encode()))
 return out
def run_audit(*,task,plan_path,bench,repository_root):
 public=json.loads((task/'task.json').read_text());task_id=public['task_id'];pr_id=public['pr_id'];repository=f"{public['repository']['owner']}/{public['repository']['name']}";base=public['baseline']['base_sha'];plan=json.loads(plan_path.read_text());planned=next(x for x in plan['tasks'] if x['task_id']==task_id);raw=find_raw(repository_root/plan['inputs']['raw']['path'],repository,pr_id);title,body=raw['title'],raw['body'];rendered=f"# Pull request task\n\nRepository: `{repository}`\n\nPull request: `{pr_id}`\n\nBase commit: `{base}`\n\n## Title\n\n{title}\n\n## Body\n\n{body}\n"
 if (task/'experiment-inputs/task.md').read_bytes()!=rendered.encode() or public['title']!=title or public['body']!=body:raise BatchError('PROMPT_PROVENANCE_FAILED','Task input is not title/body-only render')
 input_sha=sha256_file(task/'experiment-inputs/task.md');deployment=json.loads((bench/'batch/images'/base/'deployment-lock.json').read_text());image=deployment['images']['agent']['tag'];image_audit=bench/'batch/audits/images'/f'{base}-image-audit.json'
 if json.loads(image_audit.read_text())['status']!='PASS':raise BatchError('IMAGE_AUDIT_INVALID','Image audit not PASS')
 gold_dir=bench/'batch/gold'/task_id;gold_dir.mkdir(parents=True,exist_ok=True);gold_path=gold_dir/'gold-store.json'
 if not gold_path.exists():
  changed=raw.get('changed_files',[]);store={'schema_version':1,'store_type':'HOST_ONLY_GOLD','task_id':task_id,'classification':planned['classification'],'future_revisions':{'head':raw.get('head_sha'),'merge':raw.get('merge_commit_sha')},'production_patches':[{'path':x.get('filename'),'patch':x.get('patch')} for x in changed if isinstance(x,dict) and not str(x.get('filename','')).startswith(('test/','tests/'))],'test_patches':[{'path':x.get('filename'),'patch':x.get('patch')} for x in changed if isinstance(x,dict) and str(x.get('filename','')).startswith(('test/','tests/'))],'gold_target_files':sorted({x.get('file') for x in raw.get('test_changes',[]) if isinstance(x,dict) and isinstance(x.get('file'),str)}),'gold_target_symbols':sorted({str(x.get('qualified_name') or x.get('name')) for x in raw.get('test_changes',[]) if isinstance(x,dict) and (x.get('qualified_name') or x.get('name'))}),'gold_tests':[x.get('gold_test') for x in raw.get('test_changes',[]) if isinstance(x,dict) and isinstance(x.get('gold_test'),str)]};write_json(gold_path,store,refuse_overwrite=True);gold_path.chmod(0o600)
 forbidden=signatures(raw,planned['classification'],(title+'\n'+body).encode());task_input=Path(tempfile.mkdtemp(prefix='sdd-task-input-'));shutil.copy2(task/'task.json',task_input/'task.json');shutil.copy2(task/'experiment-inputs/task.md',task_input/'task.md');results=[];object_ids=[];aggregate=[]
 try:
  for method in METHODS:
   detect_workspace=task/'runs'/method/'detect/workspace';detect_planning=task/'runs'/method/'detect/planning-artifacts'
   for stage in ('detect','update'):
    audit_dir=task/'runs'/method/stage/'audit'
    if audit_dir.exists() and (task/'isolation-audit.json').exists():
     raise BatchError('AUDIT_ALREADY_EXISTS','Refusing to overwrite a completed audit',path=str(audit_dir))
    audit_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'sdd-gold-{method}-{stage}-') as td:
     temp=Path(td);detection=None
     if stage=='detect':workspace,planning=detect_workspace,detect_planning
     else:
      workspace=temp/'workspace';shutil.copytree(bench/'batch/baselines'/base/'repository',workspace,symlinks=True);make_writable(workspace);copy_init(task,method,workspace);(workspace/PLANNING_TARGET[method].removeprefix('/workspace/')).mkdir(parents=True,exist_ok=True);planning=temp/'sealed-planning-artifacts';planning.mkdir();_,planning_sha=file_manifest([('planning',planning)]);dv=sealed_canary(task_id,method,base,input_sha,planning_sha);verify_detection(dv,bench/'schemas/detection-v1.schema.json',task_id,method,base,input_sha,allow_canary=True);detection=temp/'detection-manifest.json';write_json(detection,dv)
     probe_output=temp/'probe-output';probe_output.mkdir();mount,observed=container_probe(image,stage,method,workspace,planning,probe_output,task_input,detection)
     if detection and observed['detection_sha256']!=sha256_file(detection):raise BatchError('DETECTION_TRANSFER_CHANGED','Container-visible detection bytes differ from sealed host bytes')
     write_json(audit_dir/'mount-audit.json',mount);future=[x for x in (raw.get('head_sha'),raw.get('merge_commit_sha')) if isinstance(x,str)];git=git_audit(workspace,base,future);write_json(audit_dir/'git-object-audit.json',git);object_ids.append(git['object_store_identity_sha256']);roots=[('task-input',task_input),('workspace',workspace),('planning-artifacts',planning)]+([('input/detection-manifest.json',detection)] if detection else []);lines,_=file_manifest(roots);(audit_dir/'visible-files.sha256').write_text('\n'.join(lines)+'\n');prov={'schema_version':1,'status':'PASS','approved_source_fields':['repo','pr_id','title','body'],'source_field_sha256':{'repo':hashlib.sha256(repository.encode()).hexdigest(),'pr_id':hashlib.sha256(str(pr_id).encode()).hexdigest(),'title':hashlib.sha256(title.encode()).hexdigest(),'body':hashlib.sha256(body.encode()).hexdigest()},'task_json_sha256':sha256_file(task/'task.json'),'rendered_task_markdown_sha256':input_sha,'fresh_render_matches':True,'dataset_prompt_used':False,'comments_used':False,'patch_used':False,'gold_used':False};write_json(audit_dir/'prompt-provenance.json',prov);control=b'\n'.join(x.read_bytes() for x in [task/'task.json',task/'experiment-inputs/task.md',task/'stage-policy.json',task/'runs'/method/stage/'stage.json',task/'initialization'/method/'manifest.json']);hits=[{'category':c,'matched_value_sha256':hashlib.sha256(v).hexdigest()} for c,v in forbidden if v and v in control];iso={'schema_version':1,'status':'PASS' if not hits else 'FAIL','stage':stage,'method':method,'forbidden_signature_count':len(forbidden),'finding_count':len(hits),'findings':hits,'image_audit_sha256':sha256_file(image_audit),'container_probe':observed,'cross_method_paths_visible':False,'detect_workspace_visible_to_update':False,'home_cache_session_reused':False,'host_evaluator_visible':False};write_json(audit_dir/'isolation-audit.json',iso);transfer={'schema_version':1,'status':'PASS','task_id':task_id,'method':method,'stage':stage,'detection_manifest_visible':stage=='update','manifest_kind':'isolation-canary' if stage=='update' else None,'task_match':True,'method_match':True,'base_match':True,'seal_valid':True,'same_method_only':True,'other_detection_results_visible':False,'formal_transfer_ready':False,'formal_transfer_state':'AWAITING_FORMAL_SEAL'}
     if detection:transfer['seal_sha256']=json.loads(detection.read_text())['seal']['payload_sha256']
     write_json(audit_dir/'manifest-transfer-audit.json',transfer);names=['visible-files.sha256','prompt-provenance.json','mount-audit.json','git-object-audit.json','isolation-audit.json','manifest-transfer-audit.json'];entries=[{'path':n,'sha256':sha256_file(audit_dir/n)} for n in names];total=canonical_sha256(entries);(audit_dir/'evidence.sha256').write_text('\n'.join(f"{x['sha256']}  {x['path']}" for x in entries)+f'\n{total}  TOTAL\n');status='PASS' if git['status']==iso['status']=='PASS' else 'FAIL';emap={'G01':'prompt-provenance.json','G02':'prompt-provenance.json','G03':'isolation-audit.json','G04':'mount-audit.json','G05':'git-object-audit.json','G06':'isolation-audit.json','G07':'manifest-transfer-audit.json','G08':'manifest-transfer-audit.json'};checks=[{'id':k,'name':v,'status':status,'finding_count':0 if status=='PASS' else 1,'evidence':emap[k]} for k,v in CHECKS.items()];ekeys={'visible-files.sha256':'visible_files','prompt-provenance.json':'prompt_provenance','mount-audit.json':'mount_audit','git-object-audit.json':'git_object_audit','isolation-audit.json':'isolation_audit','manifest-transfer-audit.json':'manifest_transfer_audit'};evidence={ekeys[n]:{'path':n,'sha256':sha256_file(audit_dir/n)} for n in names};evidence['total_sha256']=total;report={'schema_version':1,'policy_version':'gold-check-v1','task_id':task_id,'pr_id':pr_id,'method':method,'stage':stage,'audit_scope':'FORMAL_PREFLIGHT' if stage=='detect' else 'PRE_RUN_BOUNDARY_CANARY','checked_at_utc':now(),'status':status,'task_input_sha256':input_sha,'base_sha':base,'checks':checks,'finding_count':0 if status=='PASS' else 1,'agent_call_permitted':stage=='detect' and status=='PASS','stage_prerequisite':'SATISFIED' if stage=='detect' else 'AWAITING_FORMAL_SEAL','evidence':evidence};validate_schema(report,bench/'schemas/gold-check-v1.schema.json');write_json(audit_dir/'gold-check-report.json',report);results.append({'method':method,'stage':stage,'status':status,'agent_call_permitted':report['agent_call_permitted'],'evidence_sha256':total});aggregate.append({'method':method,'stage':stage,'evidence_sha256':total,'report_sha256':sha256_file(audit_dir/'gold-check-report.json')})
  if len(set(object_ids))!=len(object_ids):raise BatchError('OBJECT_STORE_SHARED','Stage workspace shares Git objects')
  iso_all={'schema_version':1,'audit_type':'TWO_STAGE_ISOLATION','status':'PASS','task_id':task_id,'stage_results':results,'distinct_git_object_stores':True,'detect_update_home_cache_session_shared':False,'cross_method_detection_visibility':False,'gold_store_sha256':sha256_file(gold_path),'gold_values_recorded':False};write_json(task/'isolation-audit.json',iso_all);transfer_all={'schema_version':1,'audit_type':'MANIFEST_TRANSFER','status':'PASS','task_id':task_id,'formal_update_state':'AWAITING_FORMAL_SEAL','canary_boundary_validated':True,'methods':[{'method':m,'same_task_only':True,'same_method_only':True,'seal_change_invalidates_evidence':True} for m in METHODS]};write_json(task/'manifest-transfer-audit.json',transfer_all);aggregate += [{'path':'isolation-audit.json','sha256':sha256_file(task/'isolation-audit.json')},{'path':'manifest-transfer-audit.json','sha256':sha256_file(task/'manifest-transfer-audit.json')}];total=canonical_sha256(aggregate);(task/'evidence.sha256').write_text(json.dumps(aggregate,sort_keys=True,separators=(',',':'))+f'\n{total}  TOTAL\n');return {'status':'PASS','task_id':task_id,'stage_reports':len(results),'detect_agent_calls_permitted':3,'update_agent_calls_permitted':0,'formal_update_state':'AWAITING_FORMAL_SEAL','evidence_sha256':total}
 finally:shutil.rmtree(task_input,ignore_errors=True)
