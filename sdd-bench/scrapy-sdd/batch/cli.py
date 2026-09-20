"""Command-line entry point for read-only SDD batch inventory and planning."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import (
    BatchError,
    InputPaths,
    REPOSITORY,
    build_inventory,
    create_plan,
    read_pr_id_files,
    resolve_selection,
    validate_plan_inputs,
    write_inventory,
    write_json,
)
from .provision import provision_plan
from .scaffold import scaffold_tasks
from .gold_audit import run_audit
from .compose_preflight import run_preflight
from .update_policy import select_update_policy

BENCH_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BENCH_ROOT.parents[1]
DEFAULT_PROMPT = REPOSITORY_ROOT / "output/prompt/scrapy__scrapy.json"
DEFAULT_RAW = REPOSITORY_ROOT / "output/raw_prs/scrapy__scrapy.jsonl"
DEFAULT_INVENTORY_JSON = BENCH_ROOT / "batch/inventories/scrapy-pr-inventory.json"
DEFAULT_INVENTORY_TSV = BENCH_ROOT / "batch/inventories/scrapy-pr-inventory.tsv"
DEFAULT_PLANS = BENCH_ROOT / "batch/plans"


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _add_input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prompt-input", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--raw-input", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--inventory-json", type=Path, default=DEFAULT_INVENTORY_JSON)
    parser.add_argument("--inventory-tsv", type=Path, default=DEFAULT_INVENTORY_TSV)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sdd-batch",
        description="Build Scrapy PR inventory and non-executable provision plans",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser(
        "inventory", help="Read inputs and write deterministic PR inventory files"
    )
    _add_input_arguments(inventory)

    plan = subparsers.add_parser(
        "plan", help="Resolve explicit selectors and write a review-only provision plan"
    )
    _add_input_arguments(plan)
    plan.add_argument("--source", choices=("prompt", "raw"), required=True)
    plan.add_argument("--plan-id", required=True)
    plan.add_argument("--pr-id", type=int, action="append", default=[])
    plan.add_argument("--pr-id-file", type=Path, action="append", default=[])
    plan.add_argument("--sample-id", action="append", default=[])
    plan.add_argument("--repository", default=REPOSITORY, help=argparse.SUPPRESS)
    plan.add_argument("--output", type=Path)

    validate = subparsers.add_parser(
        "validate-plan", help="Re-hash inputs and report whether a saved plan is current"
    )
    validate.add_argument("plan", type=Path)

    provision = subparsers.add_parser(
        "provision",
        help="After explicit approval, create pure baseline caches and isolated workspaces",
    )
    provision.add_argument("plan", type=Path)
    provision.add_argument("--approve-plan-id", required=True)
    provision.add_argument("--source-repository", type=Path, required=True)
    provision.add_argument("--report", type=Path)

    scaffold = subparsers.add_parser(
        "scaffold",
        help="Create frozen Detect/Update task directories after provisioning",
    )
    scaffold.add_argument("plan", type=Path)
    scaffold.add_argument("--approve-plan-id", required=True)
    scaffold.add_argument("--provision-report", type=Path)

    gold_check = subparsers.add_parser(
        "gold-check", help="Audit staged Agent visibility and gold isolation"
    )
    gold_check.add_argument("task", type=Path)
    gold_check.add_argument("--plan", type=Path, required=True)

    preflight = subparsers.add_parser(
        "preflight", help="Generate two-stage Compose deployment and run neutral runtime probes"
    )
    preflight.add_argument("task", type=Path)
    preflight.add_argument("--run-id", default="preflight-001")

    update_policy = subparsers.add_parser(
        "update-policy", help="Explicitly select sealed-detect or self-directed Update targeting"
    )
    update_policy.add_argument("task", type=Path)
    update_policy.add_argument("--method", choices=("openspec", "speckit", "cc-sdd"), required=True)
    update_policy.add_argument("--mode", choices=("sealed-detect", "self-directed"), required=True)
    update_policy.add_argument("--run-id", required=True)
    return parser.parse_args(argv)


def _failure(command: str, errors: list[dict[str, Any]]) -> int:
    _json_print(
        {
            "schema_version": 1,
            "command": command,
            "status": "INVALID_SELECTION" if command == "plan" else "ERROR",
            "plan_created": False if command == "plan" else None,
            "errors": errors,
        }
    )
    return 2


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "update-policy":
            result = select_update_policy(
                task=args.task.resolve(),
                bench=BENCH_ROOT,
                repository_root=REPOSITORY_ROOT,
                method=args.method,
                mode=args.mode,
                run_id=args.run_id,
            )
            _json_print({"schema_version": 1, "command": "update-policy", **result})
            return 0

        if args.command == "preflight":
            result = run_preflight(
                task=args.task.resolve(),
                bench=BENCH_ROOT,
                repository_root=REPOSITORY_ROOT,
                run_id=args.run_id,
            )
            _json_print({"command": "preflight", **result})
            return 0 if result["runtime_preflight_status"] == "READY" else 6

        if args.command == "gold-check":
            result = run_audit(
                task=args.task.resolve(),
                plan_path=args.plan.resolve(),
                bench=BENCH_ROOT,
                repository_root=REPOSITORY_ROOT,
            )
            _json_print({"schema_version": 1, "command": "gold-check", **result})
            return 0 if result["status"] == "PASS" else 5

        if args.command == "scaffold":
            try:
                plan = json.loads(args.plan.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return _failure("scaffold", [{"code": "INVALID_PLAN_FILE", "message": str(exc)}])
            report_path = args.provision_report or (
                BENCH_ROOT / "batch/reports" / f"{plan.get('plan_id', 'invalid')}.json"
            )
            results = scaffold_tasks(
                plan_path=args.plan,
                provision_report_path=report_path,
                approved_plan_id=args.approve_plan_id,
                bench_root=BENCH_ROOT,
                repository_root=REPOSITORY_ROOT,
            )
            _json_print({
                "schema_version": 1,
                "command": "scaffold",
                "status": "READY",
                "task_count": len(results),
                "tasks": results,
                "agents_started": False,
                "tests_run": False,
            })
            return 0

        if args.command == "provision":
            try:
                plan = json.loads(args.plan.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return _failure(
                    "provision",
                    [{"code": "INVALID_PLAN_FILE", "message": str(exc)}],
                )
            report_path = args.report or (
                BENCH_ROOT / "batch/reports" / f"{plan.get('plan_id', 'invalid')}.json"
            )
            if report_path.exists():
                return _failure(
                    "provision",
                    [
                        {
                            "code": "PROVISION_REPORT_ALREADY_EXISTS",
                            "message": "Refusing to overwrite an existing provision report",
                            "path": str(report_path),
                        }
                    ],
                )
            report = provision_plan(
                plan=plan,
                plan_path=args.plan,
                approved_plan_id=args.approve_plan_id,
                bench_root=BENCH_ROOT,
                repository_root=REPOSITORY_ROOT,
                source_repository=args.source_repository.resolve(),
            )
            write_json(report_path, report, refuse_overwrite=True)
            _json_print(
                {
                    "schema_version": 1,
                    "command": "provision",
                    "status": report["status"],
                    "report": str(report_path),
                    "task_count": report["task_count"],
                    "tests_run": False,
                    "agents_started": False,
                }
            )
            return 0 if report["status"] in {"READY", "TOPOLOGY_WARNING"} else 4

        if args.command == "validate-plan":
            try:
                plan = json.loads(args.plan.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return _failure(
                    "validate-plan",
                    [{"code": "INVALID_PLAN_FILE", "message": str(exc)}],
                )
            result = validate_plan_inputs(plan, REPOSITORY_ROOT)
            _json_print(result)
            return 0 if result["valid"] else 3

        inputs = InputPaths(prompt=args.prompt_input, raw=args.raw_input)
        for name, path in (("prompt", inputs.prompt), ("raw", inputs.raw)):
            if not path.is_file():
                return _failure(
                    args.command,
                    [
                        {
                            "code": "INPUT_NOT_FOUND",
                            "message": f"{name} input does not exist",
                            "path": str(path),
                        }
                    ],
                )
        inventory, indices = build_inventory(inputs, REPOSITORY_ROOT)
        write_inventory(inventory, args.inventory_json, args.inventory_tsv)

        if args.command == "inventory":
            _json_print(
                {
                    "schema_version": 1,
                    "command": "inventory",
                    "status": "OK",
                    "inventory_id": inventory["inventory_id"],
                    "pr_count": inventory["summary"]["pr_count"],
                    "sample_count": inventory["summary"]["sample_count"],
                    "json_path": str(args.inventory_json),
                    "tsv_path": str(args.inventory_tsv),
                }
            )
            return 0

        file_pr_ids, file_records, file_errors = read_pr_id_files(args.pr_id_file)
        requested_pr_ids = list(args.pr_id) + file_pr_ids
        resolved, events, selection_errors = resolve_selection(
            inventory,
            indices,
            source=args.source,
            pr_ids=requested_pr_ids,
            sample_ids=list(args.sample_id),
            repository=args.repository,
        )
        errors = file_errors + selection_errors
        invalid_selected = []
        by_key = {
            (pr["repository"], pr["pr_id"]): pr
            for pr in inventory["pull_requests"]
        }
        for key in resolved:
            entry = by_key.get(key)
            if entry is None or entry["classification"] == "INVALID_INPUT":
                invalid_selected.append(
                    {
                        "code": "SELECTED_PR_INVALID_INPUT",
                        "message": "Selected PR cannot produce a provision plan",
                        "details": {"repository": key[0], "pr_id": key[1]},
                    }
                )
        errors.extend(invalid_selected)
        if errors:
            return _failure("plan", errors)

        output = args.output or DEFAULT_PLANS / f"{args.plan_id}.json"
        plan = create_plan(
            plan_id=args.plan_id,
            inventory=inventory,
            inventory_path=args.inventory_json,
            source=args.source,
            requested_pr_ids=requested_pr_ids,
            pr_id_files=file_records,
            requested_sample_ids=list(args.sample_id),
            resolved=resolved,
            resolution_events=events,
            repository_root=REPOSITORY_ROOT,
        )
        write_json(output, plan, refuse_overwrite=True)
        _json_print(
            {
                "schema_version": 1,
                "command": "plan",
                "status": "AWAITING_USER_APPROVAL",
                "plan_created": True,
                "plan_id": args.plan_id,
                "path": str(output),
                "task_count": len(plan["tasks"]),
                "selected_pr_ids": [task["pr_id"] for task in plan["tasks"]],
                "executable": False,
            }
        )
        return 0
    except BatchError as exc:
        return _failure(args.command, [exc.as_dict()])
    except (OSError, ValueError) as exc:
        return _failure(
            args.command,
            [{"code": "INVALID_INPUT", "message": str(exc)}],
        )


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
