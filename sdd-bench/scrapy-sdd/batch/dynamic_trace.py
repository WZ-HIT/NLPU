"""Hash-pinned, base-derived dynamic trace inputs for fresh Detect rounds.

This adapter only verifies and publishes an existing public bundle. Collection
and diagnostic artifacts belong to the caller, outside the Agent workspace.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re

from .core import BatchError, sha256_file
from .prepare import _pinned

ENTRYPOINT = 'test-traces/README.md'
DIRECTORY = 'test-traces'
SIDECAR = 'dynamic-trace.json'
REQUIRED = {'README.md', 'query.py', 'index.json', 'symbols.json'}


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise BatchError('TRACE_DOCUMENT_INVALID', 'Unreadable trace metadata', path=str(path)) from exc
    if not isinstance(value, dict):
        raise BatchError('TRACE_DOCUMENT_INVALID', 'Trace metadata must be an object', path=str(path))
    return value


def verify_bundle(manifest_path: Path, base_sha: str) -> Path:
    """Verify every byte of an already generated public bundle; never execute it."""
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BatchError('TRACE_MANIFEST_INVALID', 'Missing or unsafe trace manifest')
    if manifest_path.parent.is_symlink():
        raise BatchError('TRACE_PATH_INVALID', 'Trace root cannot be a symbolic link')
    root = manifest_path.parent.resolve()
    manifest = _read(manifest_path)
    if (manifest.get('schema_version') != 1
            or manifest.get('document_type') != 'TEST_TRACE_BUNDLE'
            or manifest.get('base_sha') != base_sha
            or not re.fullmatch(r'[0-9a-f]{40}', base_sha)
            or any(not isinstance(manifest.get(key), str) or not manifest[key].strip()
                   for key in ('snapshot_id', 'environment_id'))
            or not isinstance(manifest.get('files'), dict)):
        raise BatchError('TRACE_IDENTITY_INVALID', 'Trace format or base identity mismatch')
    entries = list(root.rglob('*'))
    if any(path.is_symlink() or not (path.is_dir() or path.is_file()) for path in entries):
        raise BatchError('TRACE_PATH_INVALID', 'Trace bundle contains links or special files')
    expected = set(manifest['files'])
    actual = {path.relative_to(root).as_posix() for path in entries
              if path.is_file() and path != manifest_path.resolve()}
    if expected != actual or not REQUIRED <= expected:
        raise BatchError('TRACE_FILES_CHANGED', 'Trace file inventory differs from manifest')
    for relative, checksum in manifest['files'].items():
        path = PurePosixPath(relative)
        if (path.is_absolute() or '..' in path.parts or '\\' in relative
                or path.as_posix() != relative or relative == 'manifest.json'):
            raise BatchError('TRACE_PATH_INVALID', 'Unsafe trace path', path=relative)
        # Keep host diagnostics and arbitrary host files out of the public input.
        if relative not in REQUIRED and not (
                len(path.parts) == 2 and path.parts[0] in {'methods', 'instances', 'indexes'}
                and path.suffix == '.json'):
            raise BatchError('TRACE_PAYLOAD_INVALID', 'Unexpected public trace payload', path=relative)
        target = root / relative
        if (not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-f]{64}', checksum)
                or not target.resolve().is_relative_to(root) or sha256_file(target) != checksum):
            raise BatchError('TRACE_FILES_CHANGED', 'Trace file hash differs', path=relative)
    return root


def bundles(config: dict, root: Path, bases: set[str]) -> dict[str, Path]:
    augmentation = config.get('dynamic_trace')
    if augmentation is None:
        return {}
    refs = augmentation['artifacts']
    if set(refs) != bases or augmentation['entrypoint'] != ENTRYPOINT:
        raise BatchError('TRACE_SCOPE_MISMATCH', 'Trace bundles must cover exactly the selected bases')
    return {base: verify_bundle(_pinned(root, ref), base) for base, ref in refs.items()}


def verify_source_snapshot(bundle: Path, baseline_repo: Path) -> None:
    """Bind recorded source bytes and executable bits to the allowed baseline.

    Older synthetic fixtures without source_files retain their original behavior.
    Real collector bundles provide both complete source maps.
    """
    manifest = _read(bundle / 'manifest.json')
    if 'source_files' not in manifest:
        return
    files = manifest['source_files']
    executable = manifest.get('source_executable_bits')
    if (not isinstance(files, dict) or not isinstance(executable, dict)
            or set(files) != set(executable) or not baseline_repo.is_dir()):
        raise BatchError('TRACE_SOURCE_MISMATCH', 'Trace source metadata or baseline is invalid')
    root = baseline_repo.resolve()
    for relative, checksum in files.items():
        path = PurePosixPath(relative)
        if (not relative or path.is_absolute() or '..' in path.parts or '\\' in relative
                or path.as_posix() != relative or relative == '.'):
            raise BatchError('TRACE_SOURCE_PATH_INVALID', 'Unsafe recorded source path', path=relative)
        target = root / relative
        bits = executable[relative]
        if (target.is_symlink() or not target.is_file()
                or not target.resolve().is_relative_to(root)
                or any(parent.is_symlink() for parent in target.parents if parent != root and root in parent.parents)
                or not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-f]{64}', checksum)
                or type(bits) is not int or bits < 0 or bits & ~0o111
                or sha256_file(target) != checksum or target.stat().st_mode & 0o111 != bits):
            raise BatchError('TRACE_SOURCE_MISMATCH', 'Trace source differs from baseline', path=relative)


def binding(bundle: Path, base_sha: str) -> dict:
    verify_bundle(bundle / 'manifest.json', base_sha)
    return {'base_sha': base_sha, 'entrypoint': ENTRYPOINT,
            'manifest_sha256': sha256_file(bundle / 'manifest.json')}


def verify_workspace(task_root: Path, workspace: Path, base_sha: str) -> None:
    sidecar = task_root / SIDECAR
    if sidecar.is_symlink() or not sidecar.is_file():
        raise BatchError('TRACE_INPUT_CHANGED', 'Missing or unsafe frozen trace binding')
    manifest = workspace / DIRECTORY / 'manifest.json'
    verify_bundle(manifest, base_sha)
    actual = {'base_sha': base_sha, 'entrypoint': ENTRYPOINT,
              'manifest_sha256': sha256_file(manifest)}
    if _read(sidecar) != actual:
        raise BatchError('TRACE_INPUT_CHANGED', 'Frozen trace input differs from task binding')


def verify_reuse(task_root: Path, base_sha: str, expected: Path | None, methods) -> None:
    """Match requested material even when a partially scaffolded task is reused."""
    sidecar = task_root / SIDECAR
    if expected is None:
        if sidecar.exists() or sidecar.is_symlink():
            raise BatchError('TRACE_REUSE_MISMATCH', 'Existing task has unrequested trace input')
        return
    requested = binding(expected, base_sha)
    if sidecar.is_symlink() or not sidecar.is_file() or _read(sidecar) != requested:
        raise BatchError('TRACE_REUSE_MISMATCH', 'Existing task trace binding differs from request')
    for method in methods:
        verify_workspace(task_root, task_root / 'runs' / method / 'detect/workspace', base_sha)


def prompt() -> str:
    return (
        ' Frozen base-derived dynamic evidence is available at /workspace/test-traces/README.md. '
        'Read that guide and use python3 test-traces/query.py --root test-traces tests --offset 0, '
        'show TEST_ID, or reverse SYMBOL for saved coverage and observed call relations. '
        'Follow pagination for complete results. All existing tests remain searchable in the base; '
        'missing or unsuccessful traces do not remove tests from consideration. '
        'Observed execution and graph proximity do not establish required test updates. '
        'Check current source and task requirements, and do not run tests or add a production-localization stage.'
    )
