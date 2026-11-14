"""CLI entry point for collection and durable, queryable evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import TraceError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("discover", "collect", "resume"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True, type=Path)
    for name in ("aggregate", "verify", "bundle"):
        command = commands.add_parser(name)
        command.add_argument("--root", required=True, type=Path)
        if name == "bundle":
            command.add_argument("--output", required=True, type=Path)
    for name in ("show", "tests", "reverse", "summary", "export"):
        command = commands.add_parser(name, add_help=False)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    args, unknown = parser.parse_known_args()
    if args.command in {"show", "tests", "reverse", "summary", "export"}:
        # Reader has its own parser and is deliberately independent of pytest.
        import sys
        from .query import main as query
        values = sys.argv[2:]
        if "--root" in values:
            i = values.index("--root")
            values = ["--root", values[i+1], args.command, *values[:i], *values[i+2:]]
        else:
            values = [args.command, *values]
        return query(values)
    if unknown:
        parser.error("unrecognized arguments: " + " ".join(unknown))
    if args.command in {"discover", "collect", "resume"}:
        from .runner import collect, discover, load_config
        config = load_config(args.config.resolve())
        result = discover(config) if args.command == "discover" else collect(config)
        if args.command != "discover":
            from .store import aggregate
            result["summary"] = aggregate(Path(config["output"]))["summary"]
    else:
        from .store import aggregate, bundle, verify
        result = (aggregate(args.root)["summary"] if args.command == "aggregate" else verify(args.root) if args.command == "verify"
                  else bundle(args.root, args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (TraceError, ValueError, OSError) as exc:
        raise SystemExit(str(exc))
