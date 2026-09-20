"""Unified execution, readiness, reporting, and host-evaluation CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import BatchError
from .evaluator import evaluate_host
from .orchestrator import orchestrate
from .reporting import generate_final_evidence

BENCH = Path(__file__).resolve().parent.parent
ROOT = BENCH.parents[1]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sdd-pilot")
    parser.add_argument("command", choices=("detect", "update", "all", "status", "evaluate", "evaluate-host", "report"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--evaluation-plan",
        type=Path,
        default=BENCH / "batch/evaluation-plans/scrapy-3pr-prompt10-v1.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--method", choices=("openspec", "speckit", "cc-sdd"), action="append", default=[])
    parser.add_argument("--mode", choices=("sealed-detect", "self-directed"), action="append", default=[])
    parser.add_argument("--retry", action="append", default=[])
    parser.add_argument("--recover-detect", action="append", default=[])
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip the automatic result snapshot taken when the batch concludes",
    )
    args = parser.parse_args(argv)
    try:
        if args.command in {"report", "evaluate-host"}:
            controls = {
                "dry_run": args.dry_run,
                "resume": args.resume,
                "task": args.task,
                "method": args.method,
                "mode": args.mode,
                "retry": args.retry,
                "recover_detect": args.recover_detect,
                "no_archive": args.no_archive,
            }
            supplied = sorted(name for name, value in controls.items() if value)
            if supplied:
                code = "REPORT_CONTROLS_FORBIDDEN" if args.command == "report" else "EVALUATION_CONTROLS_FORBIDDEN"
                raise BatchError(
                    code,
                    "Host-only final operations always cover the complete configured experiment",
                    controls=supplied,
                )
            if args.command == "report":
                value = generate_final_evidence(
                    config_path=args.config.resolve(), bench=BENCH, repository_root=ROOT,
                )
            else:
                value = evaluate_host(
                    config_path=args.config.resolve(),
                    evaluation_plan_path=args.evaluation_plan.resolve(),
                    bench=BENCH,
                    repository_root=ROOT,
                )
        else:
            value = orchestrate(
                command=args.command, config_path=args.config.resolve(), bench=BENCH,
                repository_root=ROOT, dry_run=args.dry_run, resume=args.resume,
                retries=set(args.retry), task_ids=set(args.task), methods=set(args.method),
                modes=set(args.mode), recover_detects=set(args.recover_detect),
                archive=not args.no_archive,
            )
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get("status") in {"READY", "OK"} else 5
    except (BatchError, OSError, ValueError, json.JSONDecodeError) as exc:
        error = exc.as_dict() if isinstance(exc, BatchError) else {"code": "INVALID_INPUT", "message": str(exc)}
        print(json.dumps({"schema_version": 1, "status": "BLOCKED", "error": error}, ensure_ascii=False, indent=2))
        return 4


def main() -> None:
    raise SystemExit(run())
