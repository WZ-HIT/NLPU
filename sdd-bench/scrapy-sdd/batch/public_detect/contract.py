"""Stdlib-only public Detect validation, atomic drafts and bounded finalization.

Only explicit base source and public contracts are read. No benchmark imports,
host inventories, labels, task patches, model requests or test execution.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from pathlib import Path, PurePosixPath

VERSION = 'public-detect-v1'
MAX_VALIDATIONS = 3  # Initial check plus at most two changed-draft repairs.
TIME_RESERVE_SECONDS = 180


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def version():
    return {'version': VERSION, 'implementation_sha256': fingerprint(__file__),
            'schema_sha256': fingerprint(Path(__file__).with_name('draft.schema.json'))}


def issue(layer, code, field, message):
    return {'layer': layer, 'code': code, 'field': field, 'message': message}


def safe_path(value):
    if not isinstance(value, str) or not value:
        return False
    p = PurePosixPath(value)
    return not p.is_absolute() and '..' not in p.parts and '\\' not in value and '//' not in value and bool(p.parts) and p.parts[0] in {'test', 'tests', 'testing'}


def structure(value, protocol='testcase-v1'):
    errors = []
    if not isinstance(value, dict):
        return [issue('structure', 'DRAFT_ROOT_TYPE', '$', 'Expected an object with candidates')]
    if set(value) != {'candidates'}:
        errors.append(issue('structure', 'DRAFT_FIELDS', '$', 'Only candidates is allowed and required'))
    candidates = value.get('candidates')
    if not isinstance(candidates, list):
        return errors + [issue('structure', 'CANDIDATES_TYPE', 'candidates', 'Expected an array')]
    for i, candidate in enumerate(candidates):
        field = f'candidates[{i}]'
        if not isinstance(candidate, dict):
            errors.append(issue('structure', 'CANDIDATE_TYPE', field, 'Expected an object')); continue
        if set(candidate) != {'path', 'symbols', 'reason'}:
            errors.append(issue('structure', 'CANDIDATE_FIELDS', field, 'Expected path, symbols, reason'))
        if not safe_path(candidate.get('path')):
            errors.append(issue('structure', 'CANDIDATE_PATH', field + '.path', 'Expected a safe repository-relative test path'))
        symbols = candidate.get('symbols')
        if not isinstance(symbols, list) or any(not isinstance(s, str) or not s for s in symbols):
            errors.append(issue('structure', 'SYMBOLS_TYPE', field + '.symbols', 'Expected string array'))
        elif protocol == 'testcase-v1' and not symbols:
            errors.append(issue('structure', 'TESTCASE_SYMBOLS_REQUIRED', field + '.symbols', 'Source methods required for testcase-v1'))
        if not isinstance(candidate.get('reason'), str) or not candidate.get('reason'):
            errors.append(issue('structure', 'REASON_TYPE', field + '.reason', 'Expected a nonempty reason'))
    return errors


def identity(value, repository):
    """Validate only reported source definitions, without importing the project."""
    errors = []
    root = Path(repository).resolve()
    for i, candidate in enumerate(value['candidates']):
        field = f'candidates[{i}]'
        relative = PurePosixPath(candidate['path'])
        path = root.joinpath(*relative.parts)
        try:
            escaped = not path.resolve().is_relative_to(root)
        except (RuntimeError, OSError):
            escaped = True
        if relative.parts[0] not in {'test', 'tests'} or path.suffix != '.py' or escaped or any(p.is_symlink() for p in [path, *path.parents] if p != root and p.is_relative_to(root)):
            errors.append(issue('identity', 'SOURCE_PATH_INVALID', field + '.path', 'Expected a non-symlink Python test path within base')); continue
        try:
            import tokenize
            with tokenize.open(path) as stream:
                tree = ast.parse(stream.read())
        except (OSError, UnicodeError, SyntaxError):
            errors.append(issue('identity', 'SOURCE_UNREADABLE', field + '.path', 'Source is missing or unparseable')); continue
        definitions = Counter()

        def collect(body, scope=()):
            for node in body:
                if isinstance(node, ast.ClassDef):
                    collect(node.body, (*scope, node.name))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decorators = [ast.unparse(d.func if isinstance(d, ast.Call) else d).split('.')[-1] for d in node.decorator_list]
                    if node.name.startswith('test') and not any(d in {'fixture', 'fixturefunc'} for d in decorators):
                        definitions['.'.join((*scope, node.name))] += 1
        collect(tree.body)
        for j, symbol in enumerate(candidate['symbols']):
            if definitions[symbol] != 1:
                code = 'SOURCE_TEST_AMBIGUOUS' if definitions[symbol] > 1 else 'SOURCE_TEST_NOT_FOUND'
                errors.append(issue('identity', code, field + f'.symbols[{j}]', 'Expected one exact test source definition'))
    return errors


def validate(value, repository=None, protocol='testcase-v1'):
    errors = structure(value, protocol)
    identities = identity(value, repository) if not errors and repository is not None else []
    return {**version(), 'structure_valid': not errors, 'identity_valid': not identities if repository is not None and not errors else None,
            'errors': errors + identities, 'identity_policy': 'diagnostic; host preserves invalid-identity FP scoring'}


def atomic_json(path, value):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('SYMLINK_OUTPUT')
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reserve_status(deadline=None, remaining_tokens=None, now=None):
    now = time.time() if now is None else now
    seconds = max(0, float(deadline) - now) if deadline is not None else None
    return {'remaining_seconds': seconds, 'remaining_rollout_tokens': remaining_tokens,
            'token_status': 'UNKNOWN' if remaining_tokens is None else 'CALLER_REPORTED_NOT_ESTIMATED_FROM_CHARACTERS',
            'start_finalizing': (seconds is not None and seconds <= TIME_RESERVE_SECONDS) or (remaining_tokens is not None and remaining_tokens <= 10000),
            'time_reserve_seconds': TIME_RESERVE_SECONDS, 'automatic_publish': False}


def progress_file(directory):
    return Path(directory) / '.detect-progress' / 'progress.json'


def save_draft(directory, value, pending):
    """Incomplete draft and pending questions stay outside the formal draft."""
    path = progress_file(directory)
    old = json.loads(path.read_text()) if path.exists() else {'validation_count': 0}
    state = {**old, 'draft': value, 'pending': pending, 'phase': 'INVESTIGATING',
             'updated_at_epoch': time.time(), 'schema': VERSION}
    atomic_json(path, state)
    return {'status': 'DRAFT_SAVED', 'formal_output_written': False}


def finalize(directory, repository, protocol='testcase-v1'):
    path = progress_file(directory)
    if not path.is_file() or path.is_symlink():
        raise ValueError('DRAFT_NOT_SAVED')
    state = json.loads(path.read_text())
    if state.get('pending'):
        return {'status': 'PENDING_ITEMS', 'formal_output_written': False}
    draft = state['draft']
    key = hashlib.sha256((json.dumps(draft, sort_keys=True) + json.dumps(version(), sort_keys=True) + protocol + str(Path(repository).resolve())).encode()).hexdigest()
    if state.get('validation_key') == key:
        check = state['validation_result']
    else:
        if state.get('validation_count', 0) >= MAX_VALIDATIONS:
            return {'status': 'VALIDATION_LIMIT', 'formal_output_written': False}
        check = validate(draft, repository, protocol)
        state.update(validation_count=state.get('validation_count', 0) + 1, validation_key=key, validation_result=check)
        atomic_json(path, state)
    if not check['structure_valid'] or check['identity_valid'] is False:
        return {'status': 'VALIDATION_FAILED', 'formal_output_written': False, 'validation': check}
    # Recheck source identity on each actual publication: cached structure does not
    # authorize publishing against changed source (the frozen base is read-only).
    if identity(draft, repository):
        return {'status': 'BASE_CHANGED', 'formal_output_written': False}
    atomic_json(Path(directory) / 'detection-draft.json', draft)
    state['phase'] = 'PUBLISHED'; atomic_json(path, state)
    return {'status': 'PUBLISHED', 'formal_output_written': True, 'validation_count': state['validation_count']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['version', 'validate', 'save', 'finalize', 'status'])
    p.add_argument('--file', type=Path); p.add_argument('--repository', type=Path, default=Path('/workspace'))
    p.add_argument('--directory', type=Path); p.add_argument('--pending', action='append', default=[])
    p.add_argument('--protocol', choices=['testcase-v1', 'file-v1'], default='testcase-v1')
    p.add_argument('--remaining-tokens', type=int)
    args = p.parse_args()
    try:
        if args.command == 'version':
            result = version()
        elif args.command == 'status':
            result = reserve_status(os.environ.get('SDD_DETECT_DEADLINE_EPOCH'), args.remaining_tokens)
        elif args.command == 'validate':
            if args.file is None: p.error('--file is required')
            result = validate(json.loads(args.file.read_text()), args.repository, args.protocol)
        elif args.command == 'save':
            if args.directory is None: p.error('--directory is required')
            import sys
            result = save_draft(args.directory, json.load(sys.stdin), args.pending)
        else:
            if args.directory is None: p.error('--directory is required')
            result = finalize(args.directory, args.repository, args.protocol)
    except (ValueError, OSError) as error:
        result = {'status': 'ERROR', 'code': 'JSON_PARSE' if isinstance(error, json.JSONDecodeError) else 'IO_OR_STATE_ERROR', 'message': str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('status') not in {'ERROR', 'PENDING_ITEMS', 'VALIDATION_LIMIT', 'VALIDATION_FAILED', 'BASE_CHANGED'} and not result.get('errors') else 2


if __name__ == '__main__':
    raise SystemExit(main())
