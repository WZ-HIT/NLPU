"""Numeric-only provider usage from Codex JSONL; no prompts or gold retained.

Sum turn.completed usage, not cumulative token_count/session snapshots. Cached
input and reasoning output are subsets and must never be added to total again.
"""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .core import canonical_sha256, write_json

VERSION = 'agent-token-usage-v1'
FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
          'output_tokens', 'reasoning_output_tokens', 'total_tokens')
REQUIRED = ('input_tokens', 'output_tokens')


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def missing(status: str = 'NOT_RECORDED') -> dict[str, Any]:
    return {'schema_version': 1, 'document_type': 'AGENT_TOKEN_USAGE',
            'metric_definition_version': VERSION, 'status': status,
            'completed_turn_count': 0, 'invalid_event_count': 0,
            'source': None, **{field: None for field in FIELDS}}


@lru_cache(maxsize=512)
def _read(path_text: str, expected_sha256: str, modified_ns: int, size: int) -> dict[str, Any]:
    path = Path(path_text)
    result = missing()
    digest = hashlib.sha256()
    usages: list[dict[str, int]] = []
    started = completed = invalid = byte_count = 0
    interrupted = False
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line)
            byte_count += len(line)
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                invalid += 1
                continue
            if not isinstance(event, dict):
                invalid += 1
                continue
            kind = event.get('type')
            if kind == 'turn.started':
                started += 1
            elif kind == 'turn.failed' or kind == 'error':
                interrupted = True
            elif kind == 'turn.completed':
                completed += 1
                usage = event.get('usage')
                if not isinstance(usage, dict) or any(not _count(usage.get(k)) for k in REQUIRED):
                    invalid += 1
                    continue
                # A null optional extension means unknown. Preserve trustworthy
                # input/output even if an optional component is malformed.
                normalized = {k: usage[k] for k in REQUIRED}
                bad_optional = False
                for field in ('cached_input_tokens', 'cache_write_input_tokens', 'reasoning_output_tokens'):
                    value = usage.get(field)
                    if value is None:
                        continue
                    upper = usage['output_tokens'] if field == 'reasoning_output_tokens' else usage['input_tokens']
                    if not _count(value) or (field != 'cache_write_input_tokens' and value > upper):
                        bad_optional = True
                    else:
                        normalized[field] = value
                if bad_optional:
                    invalid += 1
                usages.append(normalized)
    changed = path.stat().st_mtime_ns != modified_ns or byte_count != size or digest.hexdigest() != expected_sha256
    result['source'] = {'path': path.name, 'sha256': digest.hexdigest(), 'size_bytes': byte_count}
    result['completed_turn_count'] = len(usages)
    result['invalid_event_count'] = invalid
    if usages:
        for field in FIELDS:
            if field == 'total_tokens':
                result[field] = sum(u['input_tokens'] + u['output_tokens'] for u in usages)
            elif all(field in u for u in usages):
                result[field] = sum(u[field] for u in usages)
        result['status'] = 'PARTIAL' if changed or invalid or interrupted or started > completed or completed != len(usages) else 'RECORDED'
    result['usage_sha256'] = canonical_sha256(result)
    return result


def read_usage(path: Path) -> dict[str, Any]:
    """Read existing evidence only. Missing usage is null, not zero."""
    try:
        if path.is_symlink() or not path.is_file():
            return missing()
        info = path.stat()
        # Some filesystems retain identical timestamps for rapid same-size
        # rewrites. Hash before cache lookup so stale usage can never survive.
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return copy.deepcopy(_read(str(path.resolve()), digest.hexdigest(), info.st_mtime_ns, info.st_size))
    except (OSError, ValueError):
        return missing('UNREADABLE')


def record_usage(path: Path, *, exit_code: int) -> dict[str, Any]:
    """Only called for the newly created current attempt, before sealing it."""
    value = read_usage(path)
    value.pop('usage_sha256', None)
    value['process_exit_code'] = exit_code
    value['usage_sha256'] = canonical_sha256(value)
    write_json(path.with_name('token-usage.json'), value, refuse_overwrite=True)
    return value


def aggregate(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(records)
    known = [r for r in values if r.get('total_tokens') is not None]
    missing_count = len(values) - len(known)
    partial_count = sum(r.get('status') != 'RECORDED' for r in known)
    result = {'attempt_count': len(values), 'recorded_attempt_count': len(known),
              'missing_attempt_count': missing_count, 'partial_attempt_count': partial_count,
              'status': 'NOT_RECORDED' if not known else ('PARTIAL' if missing_count or partial_count else 'RECORDED')}
    # For PARTIAL groups these are explicitly recorded lower-bound subtotals.
    for field in FIELDS:
        provided = [r[field] for r in known if r.get(field) is not None]
        result[field] = sum(provided) if provided else None
        if field not in REQUIRED and field != 'total_tokens' and len(provided) != len(known):
            result[field] = None
    return result
