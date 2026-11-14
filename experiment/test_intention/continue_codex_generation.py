"""Resume the sealed subscription plan without retrying terminal packets.

Optional transport recovery continues *other pending packets* after an evidenced
network failure. Sources, model, request limits and failed results stay intact.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from .recovery import atomic,coordinator,load_plan,now,sha
from .codex_recovery import RateClient,quota_allows

ROOT=Path(__file__).resolve().parents[2]
QUOTA_REASONS={'SUBSCRIPTION_LIMIT_NEAR','SUBSCRIPTION_LIMIT_REACHED','SUBSCRIPTION_QUOTA_REACHED'}
NETWORK_MARKERS=('request timed out','stream disconnected','idle timeout waiting for websocket',
                 'peer closed connection','failed to connect to websocket','connection reset')
TOOL_ITEMS={'command_execution','mcp_tool_call','web_search','file_change','collab_tool_call'}
VERSION='subscription-continuation-v3'


def active(execution):
    try:
        with coordinator(execution):pass
    except RuntimeError as exc:
        if str(exc)=='RECOVERY_ALREADY_RUNNING':return True
        raise
    return False


def next_action(status,worker_active):
    if worker_active:return 'OBSERVE_WORKER'
    if status is None:return 'START_WORKER'
    states=status.get('states',{})
    if not states.get('PENDING',0) and not states.get('NOT_SENT_BUDGET',0):return 'PREPARE_REVIEW'
    if status.get('stop_reason') in QUOTA_REASONS:return 'CHECK_QUOTA'
    return 'NEEDS_DIAGNOSIS'


def ledger_state(execution):
    """Read a consistent snapshot; never change packet or request decisions."""
    with sqlite3.connect((execution/'ledger.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        states=dict(db.execute('SELECT state,count(*) FROM packets GROUP BY state'))
        open_requests=db.execute("SELECT count(*) FROM requests WHERE state='REQUEST_STARTED'").fetchone()[0]
        row=db.execute('SELECT * FROM requests ORDER BY created DESC,id DESC LIMIT 1').fetchone()
        request=dict(row) if row else None
        packet=db.execute('SELECT state,detail FROM packets WHERE key=?',(request['key'],)).fetchone() if request else None
    return dict(states=states,open_requests=open_requests,request=request,
                packet=dict(packet) if packet else None)


def tail(path,limit=16384):
    if not path.exists():return ''
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-limit))
        return stream.read().decode('utf-8',errors='replace')


def transient_account_error(exc):
    return isinstance(exc,TimeoutError) or str(exc) in (
        'Account RPC timeout','Account RPC closed','Account RPC failed: -32603')


def read_quota():
    # __enter__ can fail after spawning app-server. Clean up that process too.
    client=RateClient()
    try:
        client.__enter__()
        return client.limits()
    finally:
        client.__exit__(None,None,None)


def transport_evidence(execution,snapshot,stop_reason,worker_log,*,worker_failed=False):
    """Recognize narrow recoverable failures; unknown/source/tool errors stop."""
    if snapshot['open_requests']:return None
    last_line=tail(worker_log).strip().splitlines()[-1:]
    if last_line and last_line[0] in (
            'RuntimeError: Account RPC failed: -32603','RuntimeError: Account RPC closed',
            'TimeoutError: Account RPC timeout'):
        return dict(code='PRE_SEND_ACCOUNT_RPC_ERROR',signature=hashlib.sha256(last_line[0].encode()).hexdigest())
    if worker_failed or (last_line and 'Error:' in last_line[0]):return None
    request,packet=snapshot['request'],snapshot['packet']
    if not request or not packet:return None
    detail=json.loads(packet['detail'])
    if stop_reason=='CLI_TIMEOUT_USAGE_UNKNOWN':
        if request['state']!='COST_UNKNOWN' or packet['state']!='COST_UNKNOWN' or detail.get('exception_type')!='TimeoutError':return None
    elif stop_reason=='CLI_FAILURE_USAGE_UNKNOWN':
        if request['state'] not in ('RESPONSE_SAVED','USAGE_UNKNOWN') or packet['state']!='FALLBACK':return None
        response=execution/'responses'/(request['id']+'.json')
        if not response.exists() or sha(response)!=request['response_sha']:return None
        saved=json.loads(response.read_text())
        if saved.get('status')!='failed' or (saved.get('incomplete_details') or {}).get('reason')!=stop_reason:return None
    else:return None
    folders=list((execution/'cli').iterdir())
    if not folders:return None
    folder=max(folders,key=lambda p:p.stat().st_mtime)
    stderr=tail(folder/'stderr.log')
    if not any(marker in stderr.lower() for marker in NETWORK_MARKERS):return None
    # A network warning must never hide unexpected tool execution.
    for line in (folder/'events.jsonl').read_text().splitlines():
        try:event=json.loads(line)
        except json.JSONDecodeError:continue
        if (event.get('item') or {}).get('type') in TOOL_ITEMS:return None
    launch=json.loads((folder/'launch.json').read_text())
    if launch.get('payload_sha256')!=request['body_sha']:return None
    return dict(code='TERMINAL_PACKET_TRANSPORT_FAILURE',signature=request['id'],
                request_id=request['id'],packet_key=request['key'],packet_state=packet['state'],
                stderr=str(folder/'stderr.log'),stderr_sha256=sha(folder/'stderr.log'))


def recovery_decision(previous,evidence,generated,epoch,maximum=3):
    """Persist a bounded backoff; progress resets the failure streak."""
    if previous.get('signature')==evidence['signature'] and generated==previous.get('generated'):
        result=dict(previous)
    else:
        progress=generated>previous.get('generated',-1)
        prior_count=0 if progress else previous.get('consecutive',0)
        # Quota RPC errors are read-only: do not spend the generation-failure
        # allowance or impose the longer generation backoff for them.
        count=prior_count if evidence.get('code')=='PRE_SEND_ACCOUNT_RPC_ERROR' else prior_count+1
        result=dict(signature=evidence['signature'],generated=generated,consecutive=count,
                    retry_at=epoch+(60 if evidence.get('code')=='PRE_SEND_ACCOUNT_RPC_ERROR' else min(60*5**(count-1),900)),evidence=evidence)
    result['action']='NEEDS_DIAGNOSIS' if result['consecutive']>=maximum else (
        'TRANSPORT_BACKOFF' if epoch<result['retry_at'] else 'CHECK_QUOTA')
    return result


def run_worker(worker,root,record):
    with (root/'worker.log').open('a') as stream:
        process=subprocess.Popen(worker,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        while process.poll() is None:
            atomic(root/'status.json',{**record,'state':'RUNNING_WORKER','worker_pid':process.pid,'updated_at':now()})
            time.sleep(60)
        return process.returncode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--execution',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--current',type=Path,required=True)
    parser.add_argument('--resume-transient-errors',action='store_true',
                        help='Skip terminal transport failures and continue pending packets with bounded backoff')
    args=parser.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    plan=args.plan.resolve();execution=args.execution.resolve()
    with coordinator(root):
        frozen=load_plan(plan)
        if frozen.get('backend')!='codex-subscription':raise ValueError('Subscription backend required')
        controller_sha=sha(Path(__file__))
        policy=dict(version=VERSION,controller_sha256=controller_sha,plan_sha256=sha(plan/'plan.json'),
                    resume_transient_errors=args.resume_transient_errors,max_consecutive_failures_without_progress=3,
                    generation_retries_for_terminal_packets=0,backoff_seconds=[60,300],poll_seconds=60)
        lock=root/'scheduler-policy.json'
        if lock.exists() and json.loads(lock.read_text())!=policy:raise ValueError('Scheduler policy changed; retain old policy before revision')
        atomic(lock,policy)
        failed_worker=False
        while True:
            if sha(Path(__file__))!=controller_sha:raise ValueError('Running scheduler source changed')
            status_path=execution/'status.json'
            status=json.loads(status_path.read_text()) if status_path.exists() else None
            worker_active=active(execution)
            snapshot=ledger_state(execution) if not worker_active and (execution/'ledger.sqlite3').exists() else None
            if snapshot is not None:
                status={**(status or {}),'states':snapshot['states']}
            action=next_action(status,worker_active)
            if failed_worker:action='NEEDS_DIAGNOSIS'
            if snapshot and snapshot['open_requests']:action='NEEDS_DIAGNOSIS'
            record=dict(state=action,updated_at=now(),execution=str(execution),plan_sha256=sha(plan/'plan.json'),
                        model=frozen['options']['model'],direct_api_cost_cny=0,worker_status=status,scheduler_version=VERSION)
            if action=='OBSERVE_WORKER':
                atomic(root/'status.json',record);time.sleep(60);continue
            if action=='NEEDS_DIAGNOSIS':
                evidence=transport_evidence(execution,snapshot,status.get('stop_reason'),root/'worker.log',worker_failed=failed_worker) if args.resume_transient_errors and snapshot else None
                if evidence:
                    retry_path=root/'recovery-state.json'
                    previous=json.loads(retry_path.read_text()) if retry_path.exists() else {}
                    retry=recovery_decision(previous,evidence,snapshot['states'].get('GENERATED',0),time.time())
                    atomic(retry_path,retry);action=retry['action'];record.update(state=action,recovery=retry)
                    if action=='TRANSPORT_BACKOFF':
                        atomic(root/'status.json',record);time.sleep(60);continue
                if action=='NEEDS_DIAGNOSIS':atomic(root/'status.json',record);return
            if action=='PREPARE_REVIEW':
                quality=root.parent/'quality'
                if not quality.exists():
                    result=subprocess.run([sys.executable,'-B','-m','experiment.test_intention.recovery_publish','sample',
                        '--plan',str(plan),'--execution',str(execution),'--current',str(args.current.resolve()),'--output',str(quality)],
                        cwd=ROOT,stdout=(root/'quality-sample.log').open('w'),stderr=subprocess.STDOUT)
                    if result.returncode:
                        record['state']='QUALITY_SAMPLE_FAILED';atomic(root/'status.json',record);return
                record['state']='READY_FOR_SOURCE_QUALITY_REVIEW';record['quality']=str(quality)
                atomic(root/'status.json',record);return
            try:limits=read_quota()
            except Exception as exc:
                if not transient_account_error(exc):
                    record.update(state='NEEDS_DIAGNOSIS',error_type=type(exc).__name__,error=str(exc));atomic(root/'status.json',record);return
                record.update(state='WAITING_QUOTA_QUERY',error_type=type(exc).__name__,error=str(exc))
                atomic(root/'status.json',record);time.sleep(60);continue
            atomic(root/'latest-quota.json',limits)
            allowed,reason=quota_allows(limits)
            if not allowed:
                record.update(state='WAITING_SUBSCRIPTION_QUOTA',reason=reason,rate_limits=limits)
                buckets=limits.get('rateLimitsByLimitId') or {'codex':limits.get('rateLimits')}
                resets=[v['resetsAt'] for b in buckets.values() if b for k in ('primary','secondary')
                        if (v:=b.get(k)) and v.get('usedPercent',0)>=95 and v.get('resetsAt')]
                if resets:
                    record['earliest_full_reset_utc']=datetime.fromtimestamp(max(resets),timezone.utc).isoformat()
                atomic(root/'status.json',record);time.sleep(60);continue
            worker=[sys.executable,'-u','-B','-m','experiment.test_intention.codex_recovery','run',
                    '--plan',str(plan),'--output',str(execution)]
            # Verify the unchanged generator, caches and plan before each resume.
            load_plan(plan)
            record['state']='RUNNING_WORKER';atomic(root/'status.json',record)
            failed_worker=False
            returncode=run_worker(worker,root,record)
            if returncode:
                failed_worker=True
                # Diagnose on the next loop. Only explicit pre-send RPC errors
                # or terminal packets with network evidence can be continued.
                record.update(state='WORKER_FAILED_NO_AUTOMATIC_RETRY',exit_code=returncode)
                atomic(root/'status.json',record)
                if not args.resume_transient_errors:return


if __name__=='__main__':main()
