"""TI-15..18: explicit recovery plan, durable accounting, no silent retries.

plan/status are offline. run requires an explicit new CNY budget and reads the
credential only at transport time. Historical caches are never modified.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import urllib.error
import urllib.request
import uuid

from .coverage_audit import STORE
from .generation import response_text
from .generation_contract import OPTIONS, INSTRUCTIONS_V2, ContractError, request_packet, validate
from .static import digest

MAX_REPAIR_BYTES = 65536
PRICING = dict(currency='CNY', input_peak_per_million=2, output_peak_per_million=8,
               cached_input_peak_per_million=.04, checked_on='2026-11-04',
               source='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
               accounting='Peak uncached formula for all tokens: conservative estimate, not invoice.')


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body(packet, previous=None, error=None, *, options=None):
    options=options or OPTIONS
    text = json.dumps(request_packet(packet), ensure_ascii=False)
    if previous is not None:
        if len(previous.encode()) > MAX_REPAIR_BYTES:
            raise ValueError('REPAIR_INPUT_LIMIT')
        message=json.dumps(error,ensure_ascii=False)
        if len(message.encode())>4096:
            raise ValueError('REPAIR_ERROR_LIMIT')
        text += '\nRepair JSON using the SAME evidence. Error: '+message
        text += '\nPrior JSON:\n'+previous
    return dict(model=options['model'], reasoning={'effort':options['effort']},
                instructions=INSTRUCTIONS_V2, input=text, store=False,
                max_output_tokens=options['max_output_tokens'], text={'format':{'type':'json_object'}})


def reservation(payload):
    # Wire UTF-8 bytes plus 1024 framing units is a conservative input estimate.
    # Integer micro-CNY avoids rounding budget gates down.
    return (len(json.dumps(payload, ensure_ascii=False).encode())+1024)*2 + payload['max_output_tokens']*8


def make_plan(audit, original, destination, workers=8):
    if destination.exists():
        raise ValueError('Refusing to overwrite recovery plan')
    summary = json.loads((audit/'summary.json').read_text())
    if summary['status'] != 'PASS':
        raise ValueError('Audit not PASS')
    old_packets = json.loads((audit/'packets.json').read_text())
    journal = json.loads((audit/'requests.json').read_text())
    by_key = defaultdict(list)
    for request in journal:
        by_key[request['input_sha256']].append(request)
    rows, reuse, evidence_errors = [], [], []
    for packet in old_packets:
        path = Path(packet['cache_path'])
        if sha(path) != packet['cache_sha256']:
            raise ValueError('Old cache changed: '+packet['cache_key'])
        raw = json.loads(path.read_text())
        if raw['status'] == 'GENERATED':
            validate(raw['result'], raw['packet'])
            reuse.append(dict(old_key=packet['cache_key'], cache_path=str(path),
                              cache_sha256=packet['cache_sha256'], options=raw['options'],
                              base_shas=packet['base_shas'], versioned_test_records=packet['versioned_test_records']))
            continue
        prior = by_key[packet['cache_key']]
        unknown = any(not r['usage_complete'] for r in prior)
        action = 'HOLD_UNKNOWN_SPEND' if unknown else 'REGENERATE_WHOLE_PACKET'
        if packet['reason'] == 'OVERSIZE_INPUT':
            action = 'HOLD_REPACK_REQUIRED'
        inputs = [raw['packet']]
        if packet['reason']=='OUTPUT_INCOMPLETE':
            # A new, explicit source-only partition. This is not salvaging
            # partial model output: every new packet still validates as a whole.
            inputs = [{**raw['packet'],'tests':[test], 'contexts':[c for c in raw['packet']['contexts']
                       if c['id'] in test['contexts']]} for test in raw['packet']['tests']]
        for source_packet in inputs:
            initial = body(source_packet)
            row = dict(old_key=packet['cache_key'], new_key=digest({'packet':source_packet,'options':OPTIONS}),
                   cache_path=str(path), cache_sha256=packet['cache_sha256'], packet_sha256=digest(source_packet),
                   packet=source_packet, partition='single-test' if len(inputs)>1 else 'original-packet',
                   base_shas=packet['base_shas'],
                   versioned_test_records=len(source_packet['tests'])*len(packet['base_shas']),
                   tests=[t['id'] for t in source_packet['tests']], reason=packet['reason'], action=action,
                   prior_attempts=raw['attempts'], prior_journal_ids=packet['request_journal_ids'],
                   origins=[{'old_key':packet['cache_key'],'base_shas':packet['base_shas']}],
                   allowed_new_requests=2 if action=='REGENERATE_WHOLE_PACKET' else 0,
                   first_request_reservation_micro_cny=reservation(initial),
                   repair_reservation_upper_micro_cny=reservation(initial)+(6*MAX_REPAIR_BYTES+32768)*2)
            rows.append(row)
        if packet['reason'] == 'EVIDENCE_REFERENCE_ERROR':
            evidence_errors.append(dict(old_key=packet['cache_key'], tests=[t['id'] for t in raw['packet']['tests']],
               test_count=len(raw['packet']['tests']), versioned_test_records=packet['versioned_test_records'],
               prior_response_ids=[a.get('response_id') for a in raw['attempts']],
               fine_grained_cause='UNKNOWN_RAW_FAILED_RESPONSE_NOT_SAVED',
               evidence_contract=[{'id':t['id'],'allowed_ids':[t['id'],*t['contexts']]} for t in raw['packet']['tests']]))
    deduplicated={}
    for row in rows:
        if row['new_key'] not in deduplicated:
            deduplicated[row['new_key']]=row
        else:
            prior=deduplicated[row['new_key']]
            prior['origins']+=row['origins']
            prior['base_shas']=sorted(set(prior['base_shas'])|set(row['base_shas']))
            prior['versioned_test_records']=len(prior['tests'])*len(prior['base_shas'])
    rows=list(deduplicated.values())
    # Round robin public base queues, deduplicating shared packets when first
    # encountered. Never use task labels, failures or per-PR localization scores.
    queues = {base:deque(sorted((r for r in rows if base in r['base_shas']),key=lambda r:r['new_key']))
              for base in sorted(summary_base_keys(audit))}
    ordered, seen = [], set()
    while any(queues.values()):
        for base, queue in queues.items():
            while queue and queue[0]['new_key'] in seen:
                queue.popleft()
            if queue:
                row = queue.popleft(); seen.add(row['new_key'])
                ordered.append(dict(row, order=len(ordered)+1, scheduled_via_base=base))
    eligible = [r for r in ordered if r['allowed_new_requests']]
    history = summary['accounting']
    plan = dict(version='ti17-recovery-plan-v1', created_at=now(), options=OPTIONS, workers=workers,
                model_calls=0, labels_read=False, original=str(original), audit=str(audit), pricing=PRICING,
                whole_packet_validation=True, partial_test_salvage=False,
                source_policy='All failed public-base packets; reuse old successful records under their original options. New prompt namespace never masquerades as old cache hits.',
                scheduling='sorted public-base round robin, shared packets dispatched once',
                maximum_validation_repairs=1, maximum_repair_reply_bytes=MAX_REPAIR_BYTES,
                historical_accounting=history, new_cost_ceiling_cny=None,
                new_budget_required=True, request_upper_bound=sum(r['allowed_new_requests'] for r in ordered),
                historical_request_journal_entries=len(journal),
                expected_restored_versioned_records=sum(r['versioned_test_records'] for r in eligible),
                historical_failed_packet_count=sum(p['status']!='GENERATED' for p in old_packets),
                recovery_packet_count=len(ordered), reused_successful_packets=len(reuse),
                first_pass_reservation_cny=sum(r['first_request_reservation_micro_cny'] for r in eligible)/1e6,
                all_one_repair_conservative_reservation_cny=sum(r['first_request_reservation_micro_cny']+
                     r['repair_reservation_upper_micro_cny'] for r in eligible)/1e6,
                forecast_note='Reservation estimates, not invoices or success promises; no new scope beyond these packets.',
                rows=ordered, reuse=reuse)
    destination.mkdir(parents=True)
    atomic(destination/'evidence-errors.json', evidence_errors)
    atomic(destination/'plan.json', plan)
    atomic(destination/'sources.json', {str(p.resolve()):sha(p) for p in
          [audit/'summary.json',audit/'packets.json',audit/'requests.json',
           audit/'coverage.json',audit/'sources.json',
           original/'scope.json',Path(__file__),Path(__file__).with_name('generation_contract.py')]})
    atomic(destination/'seal.json', {'plan_sha256':sha(destination/'plan.json'),
           'sources_sha256':sha(destination/'sources.json'), 'evidence_errors_sha256':sha(destination/'evidence-errors.json')})
    return plan


def summary_base_keys(audit):
    return [r['group'] for r in json.loads((audit/'coverage-groups.json').read_text()) if r['group_type']=='base']


def load_plan(directory):
    seal = json.loads((directory/'seal.json').read_text())
    for name, field in [('plan.json','plan_sha256'),('sources.json','sources_sha256'),('evidence-errors.json','evidence_errors_sha256')]:
        if sha(directory/name) != seal[field]:
            raise ValueError('Plan seal changed: '+name)
    for name, checksum in json.loads((directory/'sources.json').read_text()).items():
        if sha(Path(name)) != checksum:
            raise ValueError('Plan source changed: '+name)
    plan = json.loads((directory/'plan.json').read_text())
    expected_options=OPTIONS
    if plan.get('backend')=='codex-subscription':
        from .codex_recovery import OPTIONS as subscription_options
        expected_options=subscription_options
    if plan['options'] != expected_options:
        raise ValueError('Generator options changed')
    for row in plan['rows']+plan['reuse']:
        if sha(Path(row['cache_path'])) != row['cache_sha256']:
            raise ValueError('Historical cache changed')
    return plan


@contextmanager
def coordinator(root):
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.coordinator.lock').open('a+') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('RECOVERY_ALREADY_RUNNING') from None
        try:
            yield
        finally:
            fcntl.flock(lock,fcntl.LOCK_UN)


def bind_plan(directory,root,budget):
    """One sealed plan has one execution root and one durable new allowance."""
    with coordinator(directory/'execution-control'):
        path=directory/'execution-control/binding.json'
        expected=dict(plan_sha256=sha(directory/'plan.json'),execution_root=str(root.resolve()),
                      max_new_micro_cny=int(Decimal(str(budget))*1000000))
        if path.exists():
            if json.loads(path.read_text())!=expected:
                raise ValueError('PLAN_ALREADY_BOUND: reuse its original run and allowance; do not restart in another directory')
        else:
            atomic(path,expected)


class Recovery:
    def __init__(self, root, plan, *, plan_hash, max_new_cny, transport=None, secret=None):
        self.root, self.plan, self.secret = root, plan, secret
        self.options=plan.get('options',OPTIONS)
        self.subscription=plan.get('backend')=='codex-subscription'
        if len({r['new_key'] for r in plan['rows']})!=len(plan['rows']):
            raise ValueError('Duplicate recovery packet')
        self.transport = transport or http_transport
        value = Decimal(str(max_new_cny))
        if not value.is_finite() or value < 0 or (value == 0 and not self.subscription):
            raise ValueError('Explicit positive new budget required')
        self.limit = int(value*1000000)
        root.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS packets(key TEXT PRIMARY KEY,state TEXT,detail TEXT);
                CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,key TEXT,attempt INTEGER,state TEXT,
                    reservation INTEGER,accounted INTEGER,body_sha TEXT,response_sha TEXT,created TEXT,finished TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS packet_attempt ON requests(key,attempt);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,created TEXT,kind TEXT,detail TEXT);''')
            db.execute('BEGIN IMMEDIATE')
            expected = dict(plan_hash=plan_hash,max_new_micro_cny=str(self.limit),
                            max_new_calls=str(plan['request_upper_bound']))
            actual = dict(db.execute('SELECT key,value FROM metadata'))
            if actual and actual != expected:
                raise ValueError('Run identity or budget changed; explicit new plan/run required')
            db.executemany('INSERT OR IGNORE INTO metadata VALUES(?,?)',expected.items())
            db.executemany('INSERT OR IGNORE INTO packets VALUES(?,?,?)',
                           ((r['new_key'],'PENDING','{}') for r in plan['rows']))

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.root/'ledger.sqlite3',timeout=60)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self):
        with self.db() as db:
            costs=db.execute('SELECT count(*),coalesce(sum(coalesce(accounted,reservation)),0),'
                            'coalesce(sum(CASE WHEN accounted IS NULL THEN reservation ELSE 0 END),0) FROM requests').fetchone()
            states=dict(db.execute('SELECT state,count(*) FROM packets GROUP BY state'))
        return dict(new_request_count=costs[0],new_accounted_or_reserved_cny=costs[1]/1e6,
                    new_unknown_spend_reservation_cny=costs[2]/1e6,new_budget_cny=self.limit/1e6,
                    billing_mode='chatgpt-subscription' if self.subscription else 'provider-api',
                    cumulative_journal_entries=self.plan.get('historical_request_journal_entries',0)+costs[0],
                    cumulative_formula_and_reserved_cny=self.plan['historical_accounting'].get('historical_formula_cost_cny',0)+
                       self.plan['historical_accounting'].get('unknown_spend_reservation_cny',0)+costs[1]/1e6,
                    historical_accounting=self.plan['historical_accounting'],states=states)

    def state(self,key,state,detail):
        with self.db() as db:
            db.execute('UPDATE packets SET state=?,detail=? WHERE key=?',(state,json.dumps(detail),key))

    def request(self,key,attempt,payload):
        request_id=uuid.uuid4().hex; reserve=0 if self.subscription else reservation(payload)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            calls,spent=db.execute('SELECT count(*),coalesce(sum(coalesce(accounted,reservation)),0) FROM requests').fetchone()
            trigger=[]
            if calls>=self.plan['request_upper_bound']:trigger.append('REQUEST_LIMIT')
            if db.execute("SELECT count(*) FROM events WHERE kind='RESERVATION_UNDERESTIMATED'").fetchone()[0]:
                trigger.append('ACCOUNTING_REVIEW_REQUIRED')
            if spent+reserve>self.limit:trigger.append('NEW_COST_LIMIT')
            if trigger:
                detail=dict(triggers=trigger,at=now(),calls=calls,request_limit=self.plan['request_upper_bound'],
                            accounted_and_reserved_micro_cny=spent,next_reservation_micro_cny=reserve,
                            new_limit_micro_cny=self.limit)
                db.execute('INSERT INTO events(created,kind,detail) VALUES(?,?,?)',(now(),'BUDGET_REJECTED',json.dumps(detail)))
                db.execute('UPDATE packets SET state=?,detail=? WHERE key=?',('NOT_SENT_BUDGET',json.dumps(detail),key))
                return None
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?)',
                (request_id,key,attempt,'REQUEST_STARTED',reserve,None,digest(payload),None,now(),None))
        try:
            response=self.transport(payload,self.secret)
            # Store exact visible output for diagnosis/repair, not private reasoning.
            saved=dict(id=response.get('id'),model=response.get('model'),status=response.get('status'),
                       usage=response.get('usage'),text=response_text(response),
                       incomplete_details=response.get('incomplete_details'))
            atomic(self.root/'responses'/(request_id+'.json'),saved)
        except BeforeSendError as exc:
            with self.db() as db:
                db.execute('UPDATE requests SET state=?,accounted=?,finished=? WHERE id=?',('NOT_SENT',0,now(),request_id))
            self.state(key,'HOLD',{'code':'NOT_SENT_PROVIDER_SETUP','exception_type':type(exc).__name__})
            return None
        except Exception as exc:
            # A network/parse/write exception can follow a billable request.
            detail={'code':'REQUEST_COST_UNKNOWN','exception_type':type(exc).__name__}
            with self.db() as db:
                db.execute('UPDATE requests SET state=?,finished=? WHERE id=?',('COST_UNKNOWN',now(),request_id))
            self.state(key,'COST_UNKNOWN',detail)
            return None
        self.account(request_id,saved)
        return saved

    def account(self,request_id,saved):
        usage=saved.get('usage')
        valid=isinstance(usage,dict) and all(isinstance(usage.get(k),int) and not isinstance(usage.get(k),bool)
                   and usage[k]>=0 for k in ('input_tokens','output_tokens'))
        cost=(0 if self.subscription else usage['input_tokens']*2+usage['output_tokens']*8) if valid else None
        with self.db() as db:
            reserve=db.execute('SELECT reservation FROM requests WHERE id=?',(request_id,)).fetchone()[0]
            if cost is not None and cost>reserve:
                db.execute('INSERT INTO events(created,kind,detail) VALUES(?,?,?)',
                           (now(),'RESERVATION_UNDERESTIMATED',json.dumps({'request_id':request_id,'cost':cost,'reservation':reserve})))
            db.execute('UPDATE requests SET state=?,accounted=?,response_sha=?,finished=? WHERE id=?',
                ('RESPONSE_SAVED' if valid else 'USAGE_UNKNOWN',cost,
                 sha(self.root/'responses'/(request_id+'.json')),now(),request_id))

    def restore(self):
        # Called only while holding the process coordinator lock.
        with self.db() as db:
            pending=list(db.execute("SELECT id,key FROM requests WHERE state='REQUEST_STARTED'"))
        for request_id,key in pending:
            path=self.root/'responses'/(request_id+'.json')
            if path.exists():
                self.account(request_id,json.loads(path.read_text()))
            else:
                with self.db() as db:
                    db.execute('UPDATE requests SET state=?,finished=? WHERE id=?',('COST_UNKNOWN',now(),request_id))
                self.state(key,'COST_UNKNOWN',{'code':'INTERRUPTED_REQUEST_NO_RESPONSE'})

    def one(self,row):
        key=row['new_key']
        if not row['allowed_new_requests']:
            self.state(key,'HOLD',{'action':row['action']});return
        packet=row['packet']
        with self.db() as db:
            state=db.execute('SELECT state FROM packets WHERE key=?',(key,)).fetchone()[0]
            attempts=list(db.execute('SELECT id,attempt,state,response_sha FROM requests WHERE key=? ORDER BY attempt',(key,)))
        if state=='GENERATED':
            with self.db() as db:
                detail=json.loads(db.execute('SELECT detail FROM packets WHERE key=?',(key,)).fetchone()[0])
            if sha(self.root/'results'/detail['result'])!=detail['result_sha256']:
                raise ValueError('Generated recovery result changed')
            return
        if state in ('FALLBACK','COST_UNKNOWN','HOLD'):return
        previous,error=None,None
        for number in range(1,row['allowed_new_requests']+1):
            prior=next((a for a in attempts if a[1]==number),None)
            if prior:
                if prior[2] not in ('RESPONSE_SAVED','USAGE_UNKNOWN'):
                    self.state(key,'COST_UNKNOWN',{'code':'PRIOR_RESPONSE_UNKNOWN'});return
                path=self.root/'responses'/(prior[0]+'.json')
                if sha(path)!=prior[3]:raise ValueError('Saved response changed')
                response=json.loads(path.read_text())
            else:
                try:
                    payload=body(packet,previous,error,options=self.options)
                except ValueError as exc:
                    self.state(key,'FALLBACK',{'code':str(exc)});return
                response=self.request(key,number,payload)
                if response is None:return
            if response['status']!='completed':
                self.state(key,'FALLBACK',{'code':'OUTPUT_INCOMPLETE','status':response['status'],
                                           'details':response['incomplete_details']});return
            try:
                result=validate(json.loads(response['text']),packet)
            except json.JSONDecodeError as exc:
                error=dict(code='JSON_PARSE_ERROR',path='/',line=exc.lineno,column=exc.colno)
            except ContractError as exc:
                error=exc.record
            else:
                atomic(self.root/'results'/(key+'.json'),dict(status='GENERATED',input_sha256=key,
                    packet_sha256=row['packet_sha256'],options=self.options,result=result,old_key=row['old_key']))
                self.state(key,'GENERATED',{'result':key+'.json',
                           'result_sha256':sha(self.root/'results'/(key+'.json'))});return
            previous=response['text']
            with self.db() as db:
                db.execute('INSERT INTO events(created,kind,detail) VALUES(?,?,?)',
                    (now(),'VALIDATION_ERROR',json.dumps({'key':key,'attempt':number,**error})))
            # Complete response with missing usage retains a reservation and is
            # not automatically sent for another paid repair.
            usage=response.get('usage') or {}
            if not {'input_tokens','output_tokens'}<=usage.keys():
                self.state(key,'HOLD',{'code':'REPAIR_BLOCKED_UNKNOWN_USAGE','validation':error});return
        self.state(key,'FALLBACK',{'code':'VALIDATION_REPAIR_EXHAUSTED','validation':error})

    def run(self):
        with coordinator(self.root):
            self.restore()
            with ThreadPoolExecutor(max_workers=self.plan['workers']) as pool:
                for _ in pool.map(self.one,self.plan['rows']):pass
            status=self.snapshot();atomic(self.root/'status.json',status)
            return status


class BeforeSendError(ValueError):
    pass


def http_transport(payload,secret):
    if secret is None or secret.is_symlink() or not secret.is_file():
        raise BeforeSendError('Credential file missing or unsafe')
    key=secret.read_text().strip()
    if not key:raise BeforeSendError('Empty credential')
    request=urllib.request.Request('https://api.deepseek.com/responses',
          data=json.dumps(payload,ensure_ascii=False).encode(),
          headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(request,timeout=600) as stream:
        return json.load(stream)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','run','status'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--max-new-cny',type=Decimal)
    parser.add_argument('--audit',type=Path,default=STORE/'ti13-14-20261104-v1/coverage')
    parser.add_argument('--original',type=Path,default=STORE/'first30-v1')
    args=parser.parse_args()
    if args.action=='plan':
        value=make_plan(args.audit.resolve(),args.original.resolve(),args.output.resolve())
        print(json.dumps({k:v for k,v in value.items() if k not in ('rows','reuse')},ensure_ascii=False))
    elif args.action=='run':
        if args.plan is None or args.max_new_cny is None:parser.error('run needs --plan and --max-new-cny')
        plan=load_plan(args.plan.resolve())
        if not args.max_new_cny.is_finite() or args.max_new_cny<=0:parser.error('new budget must be positive and finite')
        bind_plan(args.plan.resolve(),args.output.resolve(),args.max_new_cny)
        runner=Recovery(args.output.resolve(),plan,plan_hash=sha(args.plan/'plan.json'),
             max_new_cny=args.max_new_cny,secret=Path.home()/'.config/sdd-bench/deepseek-api-key')
        print(json.dumps(runner.run(),ensure_ascii=False))
    else:
        path=args.output/'ledger.sqlite3'
        if not path.exists():
            print(json.dumps({'state':'NOT_STARTED','model_calls':0}));return
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            print(json.dumps({'states':dict(db.execute('SELECT state,count(*) FROM packets GROUP BY state')),
                              'requests':db.execute('SELECT count(*) FROM requests').fetchone()[0]}))


if __name__=='__main__':main()
