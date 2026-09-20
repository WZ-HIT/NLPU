"""Command-line entry point for the per-base image recipe generator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .image_recipes import (
    DEFAULT_TEMPLATE_SHA,
    ImageError,
    create,
    verify_all,
    verify_directory,
)

BENCH_ROOT = Path(__file__).resolve().parent.parent


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sdd-image",
        description=(
            "Generate and verify the per-base image build recipes under batch/images/: "
            "one directory per pinned base, with the base identity substituted in"
        ),
    )
    parser.add_argument(
        "--bench-root",
        type=Path,
        default=BENCH_ROOT,
        help="The bench directory to operate on (defaults to this deployment)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create",
        help="Write batch/images/<base_sha>/ from the canonical template",
    )
    create_parser.add_argument("--base-sha", required=True, metavar="SHA", help="40 lowercase hex digits")
    create_parser.add_argument(
        "--template-sha",
        default=DEFAULT_TEMPLATE_SHA,
        metavar="SHA",
        help="Recipe to copy the unrewritten files from (defaults to the canonical one)",
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="Re-derive the create-time checks against recipes on disk",
    )
    group = verify_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base-sha", metavar="SHA", help="Verify one recipe directory")
    group.add_argument(
        "--all",
        action="store_true",
        help="Verify every generated recipe, and that they differ only where the rules allow",
    )
    return parser.parse_args(argv)


def _failure(command: str, errors: list[dict[str, Any]]) -> int:
    _json_print({"schema_version": 1, "command": command, "status": "ERROR", "errors": errors})
    return 2


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bench = args.bench_root.expanduser().resolve()
    try:
        if args.command == "create":
            result = create(bench, bench.parents[1], args.base_sha, args.template_sha)
            _json_print({"schema_version": 1, "command": "create", "status": "OK", **result})
            return 0
        if args.base_sha:
            result = verify_directory(bench, args.base_sha, bench.parents[1])
            _json_print({"schema_version": 1, "command": "verify", **result})
            return 0
        result = verify_all(bench, bench.parents[1])
        _json_print({"schema_version": 1, "command": "verify", **result})
        return 0
    except ImageError as exc:
        return _failure(
            args.command,
            [{"code": exc.code, "message": exc.message, **exc.detail}],
        )
    except (OSError, ValueError, KeyError) as exc:
        return _failure(args.command, [{"code": "INVALID_INPUT", "message": str(exc)}])


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
