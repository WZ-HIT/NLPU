"""Command-line entry point for host-only batch checkpoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .checkpoint.capture import capture_pr, capture_pr_all, capture_shared, status
from .checkpoint.layout import task_ids as listed_task_ids
from .checkpoint.restore import restore_pr, restore_shared
from .checkpoint.verify import verify_pr, verify_shared
from .core import BatchError

BENCH_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BENCH_ROOT.parents[1]


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sdd-checkpoint",
        description="Capture, verify, and restore host-only batch experiment checkpoints",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="Write a checkpoint layer")
    scope = capture.add_mutually_exclusive_group(required=True)
    scope.add_argument("--shared", action="store_true", help="Capture the shared layer")
    scope.add_argument("--pr", action="append", default=[], metavar="TASK_ID")
    scope.add_argument("--pr-all", action="store_true", help="Capture every scrapy__scrapy__pr* task")
    capture.add_argument(
        "--refresh",
        action="store_true",
        help="Replace an existing checkpoint whose content changed (the old one is moved aside)",
    )
    capture.add_argument(
        "--skip-images", action="store_true", help="Do not export the pinned Docker images"
    )

    verify = subparsers.add_parser("verify", help="Re-derive every recorded hash")
    verify_scope = verify.add_mutually_exclusive_group(required=True)
    verify_scope.add_argument("--shared", action="store_true")
    verify_scope.add_argument("--pr", action="append", default=[], metavar="TASK_ID")

    restore = subparsers.add_parser("restore", help="Put captured state back on disk")
    restore_scope = restore.add_mutually_exclusive_group(required=True)
    restore_scope.add_argument("--shared", action="store_true")
    restore_scope.add_argument("--pr", action="append", default=[], metavar="TASK_ID")
    restore.add_argument("--yes", action="store_true", help="Confirm replacing live state")

    subparsers.add_parser("status", help="List captured layers and their sizes")
    return parser.parse_args(argv)


def _failure(command: str, errors: list[dict[str, Any]]) -> int:
    _json_print({"schema_version": 1, "command": command, "status": "ERROR", "errors": errors})
    return 2


def _capture(args: argparse.Namespace) -> int:
    if args.shared:
        layers = [
            capture_shared(
                bench=BENCH_ROOT,
                repository_root=REPOSITORY_ROOT,
                refresh=args.refresh,
                with_images=not args.skip_images,
            )
        ]
    else:
        targets = args.pr or (listed_task_ids(BENCH_ROOT) if args.pr_all else [])
        if not targets:
            return _failure("capture", [{"code": "NO_TASKS", "message": "No task directories found"}])
        layers = [
            capture_pr(
                bench=BENCH_ROOT,
                repository_root=REPOSITORY_ROOT,
                task_id=task_id,
                refresh=args.refresh,
            )
            for task_id in targets
        ]
    _json_print(
        {
            "schema_version": 1,
            "command": "capture",
            "layers": layers,
            "total_payload_bytes": sum(item["payload_bytes"] for item in layers),
        }
    )
    return 0


def _verify(args: argparse.Namespace) -> int:
    if args.shared:
        results = [verify_shared(bench=BENCH_ROOT, repository_root=REPOSITORY_ROOT)]
    else:
        results = [
            verify_pr(bench=BENCH_ROOT, repository_root=REPOSITORY_ROOT, task_id=task_id)
            for task_id in args.pr
        ]
    _json_print({"schema_version": 1, "command": "verify", "layers": results})
    return 0 if all(item["status"] == "PASS" for item in results) else 5


def _restore(args: argparse.Namespace) -> int:
    if args.shared:
        results = [
            restore_shared(bench=BENCH_ROOT, repository_root=REPOSITORY_ROOT, yes=args.yes)
        ]
    else:
        results = [
            restore_pr(
                bench=BENCH_ROOT,
                repository_root=REPOSITORY_ROOT,
                task_id=task_id,
                yes=args.yes,
            )
            for task_id in args.pr
        ]
    _json_print({"schema_version": 1, "command": "restore", "layers": results})
    return 0 if all(item["status"] == "PASS" for item in results) else 5


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "capture":
            return _capture(args)
        if args.command == "verify":
            return _verify(args)
        if args.command == "restore":
            return _restore(args)
        _json_print({"schema_version": 1, "command": "status", **status(BENCH_ROOT)})
        return 0
    except BatchError as exc:
        return _failure(args.command, [exc.as_dict()])
    except (OSError, ValueError) as exc:
        return _failure(args.command, [{"code": "INVALID_INPUT", "message": str(exc)}])


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
