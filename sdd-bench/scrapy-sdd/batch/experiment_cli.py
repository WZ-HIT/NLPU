"""One user-config entry point over the frozen prepare, run and host readers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .archive.viewer import ViewerUnavailable, module as viewer_module
from .core import BatchError
from .evaluator import evaluate_host
from .orchestrator import orchestrate
from .prepare import BENCH, ROOT, compile_experiment
from .prepare_run import load_prepared, prepare
from .reporting import generate_final_evidence
from .result_view import build as build_result_view, write as write_result_view


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdd-experiment", description="Prepare, run, evaluate and view one SDD experiment config")
    commands = parser.add_subparsers(dest="command", required=True)
    prepared = commands.add_parser("prepare", help="verify inputs and freeze a prepared manifest")
    prepared.add_argument("config", type=Path)
    prepared.add_argument("--output-dir", type=Path)
    prepared.add_argument("--round", help="isolated rerun label for v2 config")

    running = commands.add_parser("run", help="inspect or run targets from the frozen manifest")
    running.add_argument("config", type=Path)
    running.add_argument("--prepared-dir", type=Path)
    running.add_argument("--round", help="isolated rerun label for v2 config")
    running.add_argument("--stage", choices=("inspect", "probe", "detect", "update", "all"), default="inspect")
    running.add_argument("--execute", action="store_true", help="explicitly allow a formal Agent stage")
    running.add_argument("--resume", action="store_true")
    running.add_argument("--task", action="append", default=[])
    running.add_argument("--method", choices=("openspec", "speckit", "cc-sdd"), action="append", default=[])
    running.add_argument("--mode", choices=("sealed-detect", "self-directed"), action="append", default=[])
    running.add_argument("--retry", action="append", default=[])
    running.add_argument("--recover-detect", action="append", default=[])
    running.add_argument("--no-archive", action="store_true")

    evaluation = commands.add_parser("evaluate", help="verify compliance and optionally score on the host")
    evaluation.add_argument("config", type=Path)
    evaluation.add_argument("--prepared-dir", type=Path)
    evaluation.add_argument("--round", help="isolated rerun label for v2 config")
    evaluation.add_argument("--kind", choices=("compliance", "quality", "both", "detect"), default="compliance")

    results = commands.add_parser("results", help="read the indexed result view or historical pages")
    results.add_argument("action", choices=("summary", "list", "report", "serve"))
    results.add_argument("--config", type=Path, help="required for summary")
    results.add_argument("--prepared-dir", type=Path)
    results.add_argument("--round", help="isolated rerun label for v2 config")
    results.add_argument("--experiment", help="historical or prepared batch selector for report")
    results.add_argument("--output", type=Path)
    results.add_argument("--host", default="127.0.0.1")
    results.add_argument("--port", type=int, default=8765)
    archive = commands.add_parser("archive", help="freeze a complete gold-free round evidence package")
    archive.add_argument("config", type=Path)
    archive.add_argument("--round", required=True)
    return parser


def _compiled(config: Path) -> dict[str, Any]:
    return compile_experiment(config.resolve(), repository_root=ROOT)


def _directory(compiled: dict[str, Any], supplied: Path | None) -> Path:
    return (supplied or BENCH / "batch/prepared" / compiled["experiment_id"]).resolve()


def _frozen(config: Path, supplied: Path | None) -> tuple[dict[str, Any], Path]:
    expected = _compiled(config)
    path = _directory(expected, supplied) / "prepared-manifest.json"
    frozen = load_prepared(path, root=ROOT)
    if frozen != expected:
        raise BatchError("EXPERIMENT_MANIFEST_STALE", "Frozen manifest differs from the user config", path=str(path))
    return frozen, path


def _round_frozen(config: Path, label: str) -> tuple[dict[str, Any], Path]:
    from .rounds import load_round, round_path
    path = round_path(config, label, root=ROOT)
    return load_round(path, root=ROOT), path


def _results(args: argparse.Namespace) -> dict[str, Any] | int:
    if args.action == "summary":
        if args.config is None:
            raise BatchError("EXPERIMENT_CONFIG_REQUIRED", "Summary requires --config")
        if args.round and args.prepared_dir is not None:
            raise BatchError("ROUND_OUTPUT_FIXED", "Round output directory is fixed by its identity")
        _, path = _round_frozen(args.config, args.round) if args.round else _frozen(args.config, args.prepared_dir)
        view = build_result_view(path, BENCH, ROOT)
        return {
            "schema_version": 1, "command": "results", "status": "READY",
            "batch_id": view["batch_id"], "view_sha256": view["view_sha256"],
            "counts": view["counts"], "target_order": view["target_order"],
            "targets": view["targets"],
        }
    if args.action != "report" and (args.config is not None or args.prepared_dir is not None or args.round is not None):
        raise BatchError("EXPERIMENT_RESULTS_ARGUMENTS", "Config options apply only to results summary or report")
    if args.round and (args.config is None or args.prepared_dir is not None):
        raise BatchError("EXPERIMENT_RESULTS_ARGUMENTS", "Round report requires --config and no --prepared-dir")
    if args.action == "report" and args.prepared_dir is not None and args.config is None:
        raise BatchError("EXPERIMENT_CONFIG_REQUIRED", "Prepared directory requires --config")
    if args.action == "report" and args.config is not None and args.experiment is not None:
        raise BatchError("EXPERIMENT_RESULTS_ARGUMENTS", "Choose a config or an experiment selector")
    selector = (_round_frozen(args.config, args.round)[0] if args.round else _frozen(args.config, args.prepared_dir)[0])["prepared_id"] if args.config is not None else args.experiment
    try:
        viewer = viewer_module(BENCH)
    except ViewerUnavailable as exc:
        raise BatchError("EXPERIMENT_VIEWER_UNAVAILABLE", exc.message, **exc.details) from exc
    options = ["--bench-root", str(BENCH), args.action]
    if args.action == "report":
        if selector:
            options.append(selector)
        if args.output:
            options.extend(("--output", str(args.output)))
    elif args.action == "serve":
        options.extend(("--host", args.host, "--port", str(args.port)))
    elif args.experiment or args.output:
        raise BatchError("EXPERIMENT_RESULTS_ARGUMENTS", "Selector and output apply only to results report")
    try:
        return viewer.main(options)
    except viewer.ViewerError as exc:
        raise BatchError("EXPERIMENT_RESULTS_INVALID", str(exc)) from exc


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            if args.round:
                if args.output_dir is not None:
                    raise BatchError("ROUND_OUTPUT_FIXED", "Round output directory is fixed by its identity")
                from .rounds import prepare_round
                frozen = prepare_round(args.config.resolve(), args.round, root=ROOT)
                directory = BENCH / "batch/runs" / frozen["prepared_id"]
            else:
                compiled = _compiled(args.config)
                directory = _directory(compiled, args.output_dir)
                frozen = prepare(args.config.resolve(), directory, root=ROOT)
            value: dict[str, Any] | int = {
                "schema_version": 2 if args.round else 1, "command": "prepare", "status": "FROZEN",
                "prepared_id": frozen["prepared_id"], "target_count": frozen["target_count"],
                "manifest": str(directory / ("prepared-round.json" if args.round else "prepared-manifest.json")),
            }
        elif args.command == "run":
            if args.stage in {"detect", "update", "all"} and not args.execute:
                raise BatchError("EXPERIMENT_EXECUTE_REQUIRED", "Formal stages require --execute")
            if args.execute and args.stage in {"inspect", "probe"}:
                raise BatchError("EXPERIMENT_EXECUTE_UNUSED", "--execute applies only to formal stages")
            if args.round and args.prepared_dir is not None:
                raise BatchError("ROUND_OUTPUT_FIXED", "Round output directory is fixed by its identity")
            if args.round and args.stage in {"update", "all"}:
                raise BatchError("ROUND_DETECT_ONLY", "This round config permits Detect only")
            _, path = _round_frozen(args.config, args.round) if args.round else _frozen(args.config, args.prepared_dir)
            value = orchestrate(
                command=args.stage, manifest_path=path, config_path=None, bench=BENCH,
                repository_root=ROOT, dry_run=False, resume=args.resume,
                task_ids=set(args.task), methods=set(args.method), modes=set(args.mode),
                retries=set(args.retry), recover_detects=set(args.recover_detect),
                archive=not args.no_archive,
            )
            if args.stage != "inspect":
                view, view_path = write_result_view(path, BENCH, ROOT)
                value["result_view"] = {"path": str(view_path), "sha256": view["view_sha256"]}
        elif args.command == "evaluate":
            if args.round:
                if args.prepared_dir is not None:
                    raise BatchError("ROUND_OUTPUT_FIXED", "Round output directory is fixed by its identity")
                if args.kind not in {"compliance", "detect"}:
                    raise BatchError("ROUND_DETECT_ONLY", "Detect rounds support compliance or Detect metrics")
                frozen, path = _round_frozen(args.config, args.round)
                from .orchestrator import Ledger, _latest, _ensure_detect_barrier, validate_prepared_manifest
                config, targets = validate_prepared_manifest(path, BENCH, ROOT)
                ledger = Ledger(path.parent / "ledger.jsonl", config["batch_id"], BENCH / "schemas/batch-ledger-event-v1.schema.json")
                _ensure_detect_barrier(config=config, all_targets=targets, latest=_latest(ledger.read()), run_root=path.parent, bench=BENCH, repository_root=ROOT)
                if args.kind == "compliance":
                    report = generate_final_evidence(manifest_path=path, bench=BENCH, repository_root=ROOT)
                    value = {"schema_version": 2, "command": "evaluate", "status": "READY", "round_id": frozen["prepared_id"], "compliance": report}
                else:
                    from .detect_metrics import check
                    metrics = check(BENCH, frozen["prepared_id"])
                    value = {"schema_version": 2, "command": "evaluate", "status": "READY", "round_id": frozen["prepared_id"], "detect_metrics": metrics}
            else:
                if args.kind == "detect":
                    raise BatchError("EXPERIMENT_EVALUATION_UNAVAILABLE", "Detect metrics for v1 batches use the existing metrics command")
                frozen, path = _frozen(args.config, args.prepared_dir)
                evaluation = frozen["inputs"]["evaluation"]
                if args.kind in {"quality", "both"} and evaluation["kind"] != "host-plan":
                    raise BatchError("EXPERIMENT_EVALUATION_UNAVAILABLE", "Config does not pin a host evaluation plan")
                compliance = generate_final_evidence(manifest_path=path, bench=BENCH, repository_root=ROOT) if args.kind in {"compliance", "both"} else None
                quality = evaluate_host(
                    manifest_path=path, evaluation_plan_path=ROOT / evaluation["plan"]["path"],
                    bench=BENCH, repository_root=ROOT,
                ) if args.kind in {"quality", "both"} else None
                value = {"schema_version": 1, "command": "evaluate", "status": "READY", "prepared_id": frozen["prepared_id"], "compliance": compliance, "quality": quality}
        elif args.command == "archive":
            from .round_archive import archive_round
            _, path = _round_frozen(args.config, args.round)
            archived = archive_round(path, root=ROOT)
            value = {"schema_version": 2, "command": "archive", "status": "READY", "round_id": archived["round_id"], "archive_sha256": archived["archive_sha256"], "file_count": archived["file_count"], "archive": str(BENCH / "Log/reports/round-archives" / archived["round_id"])}
        else:
            value = _results(args)
        if isinstance(value, int):
            return value
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get("status") in {"READY", "OK", "FROZEN"} else 5
    except (BatchError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        error = exc.as_dict() if isinstance(exc, BatchError) else {"code": "INVALID_INPUT", "message": str(exc)}
        print(json.dumps({"schema_version": 1, "command": args.command, "status": "BLOCKED", "error": error}, ensure_ascii=False, indent=2))
        return 4


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
