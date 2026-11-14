"""Optional, hash-pinned base-derived representation input for fresh rounds."""
from pathlib import Path, PurePosixPath
import json

from .core import BatchError, sha256_file
from .prepare import _pinned

ENTRYPOINT = 'test-intentions/README.md'


def verify_bundle(manifest_path: Path, base_sha: str) -> Path:
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BatchError('INTENTION_MANIFEST_INVALID', 'Missing or unsafe representation manifest')
    root = manifest_path.parent.resolve()
    if any(p.is_symlink() for p in root.rglob('*')):
        raise BatchError('INTENTION_PATH_INVALID', 'Representation contains a symbolic link')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('base_sha') != base_sha or not isinstance(manifest.get('files'), dict):
        raise BatchError('INTENTION_BASE_MISMATCH', 'Representation base identity mismatch')
    expected = set(manifest['files'])
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p != manifest_path}
    if expected != actual or not {'README.md', 'index.json', 'relations.json'} <= expected:
        raise BatchError('INTENTION_FILES_CHANGED', 'Representation file inventory differs')
    for relative, checksum in manifest['files'].items():
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts or '\\' in relative:
            raise BatchError('INTENTION_PATH_INVALID', 'Unsafe representation path')
        target = root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(root) or sha256_file(target) != checksum:
            raise BatchError('INTENTION_FILES_CHANGED', 'Representation source changed', path=relative)
    return root


def bundles(config: dict, root: Path, bases: set[str]) -> dict[str, Path]:
    augmentation = config.get('test_intention')
    if augmentation is None:
        return {}
    refs = augmentation['artifacts']
    if set(refs) != bases or augmentation['entrypoint'] != ENTRYPOINT:
        raise BatchError('INTENTION_SCOPE_MISMATCH', 'Representations must cover exactly the selected bases')
    return {base: verify_bundle(_pinned(root, ref), base) for base, ref in refs.items()}
