"""Command-line entry point for the experiment result archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .archive.snapshot import archive_selected, list_snapshots, status
from .archive.verify import verify
from .archive.viewer import ViewerUnavailable
from .core import BatchError

BENCH_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BENCH_ROOT.parents[1]


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sdd-archive",
        description="Archive rendered experiment results so they outlive the experiment tree",
    )
    parser.add_argument(
        "--bench-root",
        type=Path,
        default=BENCH_ROOT,
        help="The bench directory to operate on (defaults to this deployment)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    archive = subparsers.add_parser("archive", help="Write snapshots for one or more experiments")
    selection = archive.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--experiment",
        action="append",
        default=[],
        metavar="ID",
        help=(
            "An experiment id or unambiguous fragment. Naming a batch archives that "
            "batch's whole card set; naming a per-PR card archives just that card"
        ),
    )
    selection.add_argument("--all", action="store_true", help="Every discovered batch experiment")
    archive.add_argument(
        "--force",
        action="store_true",
        help=(
            "Archive even when the experiment has not concluded. This is the only way to "
            "preserve a run that is still in flight; the recorded outcome says so"
        ),
    )
    archive.add_argument(
        "--refresh",
        action="store_true",
        help="Re-render even when nothing changed; the previous snapshot is kept",
    )

    subparsers.add_parser("status", help="Summarize what has been archived")
    subparsers.add_parser("list", help="List every archived snapshot")
    subparsers.add_parser("verify", help="Re-derive every recorded snapshot hash")
    return parser.parse_args(argv)


def _failure(command: str, errors: list[dict[str, Any]]) -> int:
    _json_print({"schema_version": 1, "command": command, "status": "ERROR", "errors": errors})
    return 2


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bench = args.bench_root.expanduser().resolve()
    repository_root = bench.parents[1]
    try:
        if args.command == "archive":
            value = archive_selected(
                bench=bench,
                repository_root=repository_root,
                selectors=list(args.experiment),
                everything=args.all,
                force=args.force,
                refresh=args.refresh,
            )
            _json_print({"schema_version": 1, "command": "archive", **value})
            return 0
        if args.command == "verify":
            result = verify(bench, repository_root)
            _json_print({"schema_version": 1, "command": "verify", **result})
            return 0 if result["status"] == "PASS" else 5
        if args.command == "list":
            _json_print({"schema_version": 1, "command": "list", **list_snapshots(bench)})
            return 0
        _json_print({"schema_version": 1, "command": "status", **status(bench)})
        return 0
    except BatchError as exc:
        return _failure(args.command, [exc.as_dict()])
    except ViewerUnavailable as exc:
        return _failure(args.command, [exc.as_dict()])
    except (OSError, ValueError) as exc:
        return _failure(args.command, [{"code": "INVALID_INPUT", "message": str(exc)}])


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
