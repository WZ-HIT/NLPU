"""CLI adapters for the Detect and Update stage launchers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .core import BatchError
from .stages import detect_targets, update_tests

BENCH = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BENCH.parents[1]


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _error(command: str, exc: BatchError | Exception) -> int:
    value = exc.as_dict() if isinstance(exc, BatchError) else {
        "code": "UNEXPECTED_ERROR", "message": str(exc)
    }
    _print({"schema_version": 1, "command": command, "status": "BLOCKED", "error": value})
    return 4


def detect_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sdd-detect-targets")
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--method", choices=("openspec", "speckit", "cc-sdd"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recover-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = detect_targets(
            task_manifest=args.task_manifest.resolve(), method=args.method,
            run_id=args.run_id, output=args.output, bench=BENCH,
            repository_root=REPOSITORY_ROOT, dry_run=args.dry_run,
            recover_existing=args.recover_existing,
        )
        _print({"command": "sdd-detect-targets", **result})
        return 0
    except (BatchError, OSError, ValueError, json.JSONDecodeError) as exc:
        return _error("sdd-detect-targets", exc)


def update_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sdd-update-tests")
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--update-policy", type=Path, required=True)
    parser.add_argument("--expected-policy-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = update_tests(
            task_manifest=args.task_manifest.resolve(),
            policy_path=args.update_policy.resolve(), output=args.output,
            bench=BENCH, repository_root=REPOSITORY_ROOT, dry_run=args.dry_run,
            expected_policy_sha256=args.expected_policy_sha256,
        )
        _print({"command": "sdd-update-tests", **result})
        return 0 if result["status"] != "BLOCKED" else 5
    except (BatchError, OSError, ValueError, json.JSONDecodeError) as exc:
        return _error("sdd-update-tests", exc)
