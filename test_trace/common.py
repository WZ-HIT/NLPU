"""Small, standard-library-only persistence and identity helpers."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class TraceError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def atomic_text(path: Path, value: str, *, durable: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def safe_relative(value: str) -> str:
    path = Path(value)
    if (not value or path.is_absolute() or ".." in path.parts or "\\" in value
            or path.as_posix() != value or value == "."):
        raise TraceError(f"Unsafe relative path: {value!r}")
    return value


def snapshot(repository: Path) -> dict[str, Any]:
    """Pin all regular input files, without importing the project or reading Git history."""
    ignored = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
    files = {}
    executable_bits = {}
    for current, directories, names in os.walk(repository):
        directories[:] = sorted(d for d in directories if d not in ignored and not (Path(current) / d).is_symlink())
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink():
                raise TraceError(f"Snapshot contains a symbolic link: {path}")
            if path.is_file():
                relative = path.relative_to(repository).as_posix()
                files[relative] = file_hash(path)
                executable_bits[relative] = path.stat().st_mode & 0o111
    return {"snapshot_id": digest({"files": files, "executable_bits": executable_bits}),
            "files": files, "executable_bits": executable_bits}
