"""Bounded, atomic investigation notes. No labels, model calls, or scoring changes."""
import argparse
import fcntl
import json
from pathlib import Path
import sys

if __package__:
    from . import contract
else:
    import contract

VERSION = 'candidate-decisions-v1'
MAX_RECORDS, MAX_UPDATES, MAX_BYTES = 256, 3, 2200
FIELDS = {'id', 'task_requirement', 'state', 'edit_scope', 'method_edit_reason',
          'support', 'against', 'unknowns', 'exposure'}
SCOPES = ('method_content', 'helper_only', 'test_identity_change', 'new_test', 'unknown')
STATES = ('selected', 'excluded', 'pending')
EXPOSURES = ('name_only', 'complete_result', 'source_expanded')


def issues(value, repository=None):
    errors = []
    def error(code, field):
        errors.append({'code': code, 'field': field})
    if not isinstance(value, dict) or set(value)!=FIELDS:
        return [{'code': 'DECISION_FIELDS', 'field': '$'}]
    for field, limit in (('id', 512), ('task_requirement', 240), ('method_edit_reason', 300)):
        if not isinstance(value[field], str) or not 1<=len(value[field])<=limit:
            error('DECISION_TEXT', field)
    for field, allowed in (('state', STATES), ('edit_scope', SCOPES)):
        if value[field] not in allowed:
            error('DECISION_ENUM', field)
    for field in ('support', 'against', 'unknowns'):
        entries = value[field]
        if not isinstance(entries, list) or len(entries)>3 or any(not isinstance(s,str) or not 1<=len(s)<=240 for s in entries):
            error('DECISION_LIST', field)
    exposure = value['exposure']
    if (not isinstance(exposure, dict) or set(exposure)!={'stage','refs'} or
        exposure.get('stage') not in EXPOSURES or not isinstance(exposure.get('refs'), list) or
        not exposure['refs'] or len(exposure['refs'])>3 or
        any(not isinstance(s,str) or not 1<=len(s)<=240 for s in exposure['refs'])):
        error('DECISION_EXPOSURE', 'exposure')
    if value['state']=='selected' and (value['edit_scope']!='method_content' or not value['support']):
        error('SELECTED_REQUIRES_METHOD_SUPPORT', 'state')
    if len(json.dumps(value, ensure_ascii=False, separators=(',',':')).encode())>MAX_BYTES:
        error('DECISION_SIZE', '$')
    if not errors:
        if '::' not in value['id']:
            error('DECISION_ID', 'id')
        else:
            path, symbol = value['id'].split('::',1)
            draft = {'candidates':[{'path':path,'symbols':[symbol],'reason':'investigation identity'}]}
            result = contract.validate(draft, repository, 'testcase-v1')
            errors += [{'code':e['code'], 'field':'id'} for e in result['errors']]
    return errors


def store_path(directory):
    directory = Path(directory)
    if directory.is_symlink() or any(p.is_symlink() for p in directory.parents):
        raise ValueError('SYMLINK_OUTPUT')
    path = directory/'.detect-progress/candidate-decisions.json'
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('SYMLINK_OUTPUT')
    return path


def save(directory, value, repository):
    errors = issues(value, repository)
    if errors:
        return {'saved': False, 'errors': errors}
    path = store_path(directory)
    path.parent.mkdir(parents=True,exist_ok=True)
    lock=path.with_suffix('.lock')
    if lock.is_symlink():raise ValueError('SYMLINK_OUTPUT')
    with lock.open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        return _save_locked(path,value)


def _save_locked(path,value):
    state = json.loads(path.read_text()) if path.exists() else {'version':VERSION,'records':{}}
    if state.get('version')!=VERSION or not isinstance(state.get('records'),dict):
        raise ValueError('DECISION_STORE_VERSION')
    records = state['records']; identity = value['id']; prior = records.get(identity)
    if prior and prior['record']==value:
        return {'saved':True, 'unchanged':True, 'revision':prior['revision']}
    if not prior and len(records)>=MAX_RECORDS:
        raise ValueError('DECISION_RECORD_LIMIT')
    revision = prior['revision']+1 if prior else 1
    if revision>MAX_UPDATES:
        raise ValueError('DECISION_UPDATE_LIMIT')
    # Retain up to three revisions for timeline diagnosis; interrupted replace preserves old state.
    history = prior.get('history',[])+[prior['record']] if prior else []
    records[identity] = {'revision':revision, 'record':value, 'history':history}
    contract.atomic_json(path, state)
    return {'saved':True, 'revision':revision, 'records':len(records)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('save','status'))
    parser.add_argument('--directory', required=True)
    parser.add_argument('--repository')
    args=parser.parse_args()
    try:
        if args.command=='save':
            if not args.repository:
                parser.error('save requires --repository')
            payload=sys.stdin.buffer.read(MAX_BYTES+4096)
            if len(payload)>MAX_BYTES+4095:
                raise ValueError('DECISION_INPUT_SIZE')
            result=save(args.directory,json.loads(payload),args.repository)
        else:
            path=store_path(args.directory)
            state=json.loads(path.read_text()) if path.exists() else {'records':{}}
            result={'version':VERSION, 'record_count':len(state['records']),
                    'limits':{'records':MAX_RECORDS,'updates_per_candidate':MAX_UPDATES,'bytes_per_record':MAX_BYTES}}
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result.get('saved',True) else 1
    except (OSError,ValueError) as exc:
        print(json.dumps({'saved':False,'errors':[{'code':str(exc)[:160],'field':'$'}]}))
        return 1


if __name__=='__main__':
    sys.exit(main())
