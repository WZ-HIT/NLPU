"""Immutable host-only evidence package; raw gold stores stay outside it."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .core import BatchError, canonical_sha256, sha256_file, write_json
from .result_view import load as load_view
from .rounds import load_round


def _files(root: Path, round_root: Path, manifest: dict[str, Any]) -> list[Path]:
    paths = {root / ref['path'] for ref in manifest['evidence']}
    from .detect_metrics import document_path
    metrics = document_path(root / 'sdd-bench/scrapy-sdd', manifest['prepared_id'])
    if metrics.is_file():
        paths.add(metrics)
    excluded = {'workspace', 'gold', 'secrets', 'credentials'}
    for current, directories, filenames in os.walk(round_root, followlinks=False):
        parent = Path(current)
        for name in list(directories):
            child = parent / name
            if name in excluded:
                directories.remove(name)
            elif child.is_symlink():
                raise BatchError('ROUND_ARCHIVE_SYMLINK', 'Round evidence contains a symlink', path=str(child))
        for name in filenames:
            if name in {'.env', 'api-key'} or name in excluded:
                continue
            path = parent / name
            if path.is_symlink():
                raise BatchError('ROUND_ARCHIVE_SYMLINK', 'Round evidence contains a symlink', path=str(path))
            if path.is_file():
                paths.add(path)
    for path in paths:
        relative = path.relative_to(root)
        if 'gold' in relative.parts or 'workspace' in relative.parts or path.is_symlink() or not path.is_file():
            raise BatchError('ROUND_ARCHIVE_UNSAFE', 'Archive source is unsafe', path=str(path))
    return sorted(paths)


def verify_archive(path: Path) -> dict[str, Any]:
    manifest_path = path / 'archive-manifest.json'
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise BatchError('ROUND_ARCHIVE_MISSING', 'Archive manifest is missing')
    document = json.loads(manifest_path.read_text(encoding='utf-8'))
    schema_path = Path(__file__).resolve().parent.parent / 'schemas/round-archive-v1.schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    errors = list(Draft202012Validator(schema).iter_errors(document))
    if errors:
        raise BatchError('ROUND_ARCHIVE_SCHEMA_INVALID', errors[0].message)
    if document['file_count'] != len(document['files']):
        raise BatchError('ROUND_ARCHIVE_COUNT_INVALID', 'Archive file count differs')
    supplied = document.get('archive_sha256')
    payload = dict(document); payload.pop('archive_sha256', None)
    if supplied != canonical_sha256(payload):
        raise BatchError('ROUND_ARCHIVE_HASH_INVALID', 'Archive manifest hash differs')
    names = [item['path'] for item in document['files']]
    if names != sorted(set(names)):
        raise BatchError('ROUND_ARCHIVE_ORDER_INVALID', 'Archive paths must be unique and sorted')
    actual = sorted(item.relative_to(path / 'files').as_posix() for item in (path / 'files').rglob('*') if item.is_file())
    if actual != names:
        raise BatchError('ROUND_ARCHIVE_CONTENT_INVALID', 'Archive contains an unlisted or missing file')
    for item in document['files']:
        relative = Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise BatchError('ROUND_ARCHIVE_PATH_INVALID', 'Archive path escapes')
        candidate = path / 'files' / relative
        if candidate.is_symlink() or not candidate.is_file() or sha256_file(candidate) != item['sha256']:
            raise BatchError('ROUND_ARCHIVE_FILE_CHANGED', 'Archived file hash differs', path=item['path'])
    return document


def _archive_round_locked(manifest_path: Path, *, root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest = load_round(manifest_path, root=root)
    round_root = manifest_path.parent.resolve()
    view = load_view(round_root / 'result-view.json', root / 'sdd-bench/scrapy-sdd', root)
    if view['counts']['target_count'] != manifest['target_count'] or view['counts']['terminal_count'] != manifest['target_count']:
        raise BatchError('ROUND_ARCHIVE_INCOMPLETE', 'Every Detect target must be sealed before archive')
    if any(row['state'] != 'DETECT_SEALED' for row in view['targets'].values()):
        raise BatchError('ROUND_ARCHIVE_INCOMPLETE', 'A Detect target is not sealed')
    from .detect_metrics import document_path
    if not (round_root / 'final/report.json').is_file() or not document_path(root / 'sdd-bench/scrapy-sdd', manifest['prepared_id']).is_file():
        raise BatchError('ROUND_ARCHIVE_INCOMPLETE', 'Compliance report and Detect metrics must be generated before archive')
    archive_root = root / 'sdd-bench/scrapy-sdd/Log/reports/round-archives'
    destination = archive_root / manifest['prepared_id']
    if destination.exists():
        existing = verify_archive(destination)
        if existing['round_id'] != manifest['prepared_id'] or existing['result_view_sha256'] != view['view_sha256']:
            raise BatchError('ROUND_ARCHIVE_CONFLICT', 'Existing archive belongs to different evidence')
        return existing
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_root.chmod(0o700)
    temp = Path(tempfile.mkdtemp(prefix='.round-archive-', dir=archive_root))
    try:
        records = []
        for source in _files(root, round_root, manifest):
            relative = source.relative_to(root)
            target = temp / 'files' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if sha256_file(source) != sha256_file(target):
                raise BatchError('ROUND_ARCHIVE_COPY_CHANGED', 'Source changed during archive', path=relative.as_posix())
            records.append({'path': relative.as_posix(), 'sha256': sha256_file(target), 'size_bytes': target.stat().st_size})
        document: dict[str, Any] = {'schema_version': 1, 'archive_type': 'ISOLATED_DETECT_ROUND',
                                    'round_id': manifest['prepared_id'], 'result_view_sha256': view['view_sha256'],
                                    'file_count': len(records), 'files': records}
        document['archive_sha256'] = canonical_sha256(document)
        write_json(temp / 'archive-manifest.json', document, refuse_overwrite=True)
        os.replace(temp, destination)
        return verify_archive(destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def archive_round(manifest_path: Path, *, root: Path) -> dict[str, Any]:
    """Archive only while no runner can append to this round ledger."""
    from .orchestrator import _run_duration_lock
    round_id = manifest_path.parent.name
    with _run_duration_lock(manifest_path.parent, round_id):
        return _archive_round_locked(manifest_path, root=root)
