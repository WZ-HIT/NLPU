"""Read-only verification of archived snapshots.

Verification answers one question: are the bytes on disk still the bytes the
manifest recorded? It re-hashes every snapshot rather than trusting the record,
and it re-checks that each recorded path still resolves inside the archive root.

It deliberately does *not* try to reproduce ``content_sha256``. That digest
describes the experiment state a snapshot was taken from, and the whole point of
the archive is to outlive that state. A snapshot whose source has since been
re-run or deleted is still a valid archive of what was true when it was taken;
re-deriving the digest would report that as damage and train the reader to
ignore the result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core import BatchError, sha256_file
from . import layout


def _schema_validate(bench: Path, document: dict[str, Any]) -> None:
    from jsonschema import Draft202012Validator

    schema_path = layout.schema_path(bench)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.path)
    )
    if errors:
        raise BatchError(
            "ARCHIVE_SCHEMA_INVALID",
            "The archive manifest failed schema validation",
            schema=str(schema_path),
            errors=[
                f"{'/'.join(str(part) for part in error.path)}: {error.message}"
                for error in errors[:20]
            ],
        )


def _record(checks: list[dict[str, Any]], name: str, status: str, **detail: Any) -> None:
    checks.append({"check": name, "status": status, **detail})


def verify(bench: Path, repository_root: Path) -> dict[str, Any]:
    path = layout.manifest_path(bench)
    if not path.is_file():
        return {
            "schema_version": 1,
            "status": "PASS",
            "snapshot_count": 0,
            "checks": [],
            "failed_count": 0,
            "note": "Nothing has been archived yet",
        }
    document = json.loads(path.read_text(encoding="utf-8"))
    _schema_validate(bench, document)

    checks: list[dict[str, Any]] = []
    root = layout.archive_root(bench).resolve()
    for record in document["snapshots"]:
        name = record["snapshot_id"]
        target = (repository_root / record["path"]).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            _record(checks, name, "FAIL", reason="path escapes the archive root", path=record["path"])
            continue
        if not target.is_file():
            _record(checks, name, "FAIL", reason="snapshot file is missing", path=record["path"])
            continue
        actual = sha256_file(target)
        if actual != record["html_sha256"]:
            _record(
                checks,
                name,
                "FAIL",
                reason="html sha256 differs",
                recorded=record["html_sha256"],
                actual=actual,
            )
            continue
        size = target.stat().st_size
        if size != record["html_bytes"]:
            _record(checks, name, "FAIL", reason="size differs", recorded=record["html_bytes"], actual=size)
            continue
        _record(checks, name, "PASS", outcome=record["outcome"], html_bytes=size)

    failed = [item for item in checks if item["status"] == "FAIL"]
    return {
        "schema_version": 1,
        "status": "PASS" if not failed else "FAIL",
        "manifest_path": str(path),
        "snapshot_count": document["snapshot_count"],
        "checks": checks,
        "failed_count": len(failed),
    }
