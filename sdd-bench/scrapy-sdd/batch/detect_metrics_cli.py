"""Command-line entry point for the Detect hit-rate metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .archive.viewer import ViewerUnavailable
from .core import BatchError
from .detect_metrics import check, rollup, show, status

BENCH_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BENCH_ROOT.parents[1]


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sdd-detect-metrics",
        description=(
            "Score the sealed Detect output of a batch against the host-only gold: "
            "how many of the reported test files the pull request actually changed"
        ),
    )
    parser.add_argument(
        "--bench-root",
        type=Path,
        default=BENCH_ROOT,
        help="The bench directory to operate on (defaults to this deployment)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("check", "Compute the metrics and record them for one batch"),
        ("show", "Print the recorded metrics for one batch, without recomputing"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--batch", required=True, metavar="ID", help="The batch id")

    check_parser = subparsers.choices["check"]
    check_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print without writing; shows whether a re-run would change the numbers",
    )
    check_parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit 5 when any target errored. Missing gold is not an error and does not "
            "trigger this: it is a fact about the task, not a failure of the run"
        ),
    )

    rollup_parser = subparsers.add_parser(
        "rollup",
        help="Union the recorded reports of several batches into one table",
    )
    rollup_parser.add_argument(
        "--batch", required=True, action="append", metavar="ID", dest="batches",
        help="A batch id; repeat for each source, at least twice",
    )
    rollup_parser.add_argument(
        "--as", required=True, metavar="ID", dest="rollup_id",
        help="Name for the rollup, and the stem of the files it writes",
    )
    rollup_parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute and print without writing; shows whether a re-run would change the numbers",
    )

    subparsers.add_parser("status", help="List every recorded batch report")
    return parser.parse_args(argv)


def _failure(command: str, errors: list[dict[str, Any]]) -> int:
    _json_print({"schema_version": 1, "command": command, "status": "ERROR", "errors": errors})
    return 2


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bench = args.bench_root.expanduser().resolve()
    try:
        if args.command == "check":
            result = check(bench, args.batch, dry_run=args.dry_run)
            _json_print({"schema_version": 1, "command": "check", **result})
            if args.strict and result["counts"]["error_count"]:
                return 5
            return 0
        if args.command == "rollup":
            _json_print({
                "schema_version": 1, "command": "rollup",
                **rollup(bench, args.batches, args.rollup_id, dry_run=args.dry_run),
            })
            return 0
        if args.command == "show":
            document = show(bench, args.batch)
            # The document is spread at the top level on purpose: it already
            # carries schema_version 1, and a reader piping `show` should not have
            # to unwrap an envelope to reach rows and methods.
            _json_print({"command": "show", **document})
            return 0
        _json_print({"schema_version": 1, "command": "status", **status(bench)})
        return 0
    except (BatchError, ViewerUnavailable) as exc:
        return _failure(args.command, [exc.as_dict()])
    except (OSError, ValueError) as exc:
        return _failure(args.command, [{"code": "INVALID_INPUT", "message": str(exc)}])


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
