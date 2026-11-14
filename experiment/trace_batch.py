"""Durable, bounded orchestration of caller-pinned per-base trace jobs.

Preparation selects only PR ids/base SHAs. Collection never reads update labels.
The frozen copy of this file supervises frozen collector code in subprocesses.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import concurrent.futures
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from test_trace.common import atomic_text, digest, file_hash, read_json, write_json
from test_trace.runner import _remove_tree, collect, coordinator_lock, discover, load_config
from test_trace.store import bundle, verify


def make_scope(rows):
    pairs = sorted(({"pr_id": row["pr_id"], "base_sha": row["base_sha"]} for row in rows), key=lambda r: r["pr_id"])
    if len({r["pr_id"] for r in pairs}) != len(pairs):
        raise ValueError("Duplicate PR identity")
    if any(not isinstance(r["pr_id"], int) or len(r["base_sha"]) != 40
           or any(c not in "0123456789abcdef" for c in r["base_sha"]) for r in pairs):
        raise ValueError("Invalid PR/base identity")
    return {"pull_requests": pairs, "scope_sha256": digest(pairs)}


def prepare(args):
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "plan.json").exists():
        raise ValueError("Plan already frozen; use its existing run command")
    scope = make_scope(read_json(args.retrieval_run / "per-pr.json"))
    by_base = defaultdict(list)
    for row in scope["pull_requests"]:
        by_base[row["base_sha"]].append(row["pr_id"])
    bench = args.benchmark.resolve()
    sys.path.insert(0, str(bench))
    from batch.testcase_identity import verified_baseline
    image_map = read_json(args.image_map) if args.image_map else {}
    names = [image_map.get(b, args.image_template.format(base=b)) for b in sorted(by_base)]
    image_result = subprocess.run(["docker", "image", "inspect", *names], capture_output=True, text=True, check=True)
    images = json.loads(image_result.stdout)
    if len(images) != len(by_base):
        raise ValueError("Missing pre-existing base image")
    reuse = {}
    external = read_json(args.external_terminal_map) if args.external_terminal_map else {}
    if not set(external) <= set(by_base):
        raise ValueError("External job base outside selected scope")
    for path in args.reuse_bundle:
        verified = verify(path)
        manifest = read_json(path / "manifest.json")
        base = manifest["base_sha"]
        if base not in by_base or base in reuse or not verified["summary"]["dataset_complete"]:
            raise ValueError("Reused bundle must be complete, unique and in scope")
        reuse[base] = {"bundle": str(path.resolve()), "manifest_sha256": file_hash(path / "manifest.json"),
                       "summary": verified["summary"], "status": "REUSED_VERIFIED", "verification": verified}
    code = root / "code"
    code.mkdir()
    shutil.copytree(Path(__file__).parents[1] / "test_trace", code / "test_trace", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(Path(__file__), code / "batch_driver.py")
    code_files = {p.relative_to(code).as_posix(): file_hash(p) for p in sorted(code.rglob("*")) if p.is_file()}
    jobs = []
    for base, image in zip(sorted(by_base), images):
        repository, lock = verified_baseline(bench, base)
        baseline = read_json(bench.parents[1] / lock["path"])
        for entry in baseline["checkout_files"]:
            source = repository / entry["path"]
            if source.is_symlink() or not source.is_file() or file_hash(source) != entry["sha256"]:
                raise ValueError("Base source differs from its frozen checkout: " + str(source))
            if bool(source.stat().st_mode & 0o111) != (entry["mode"] == "100755"):
                raise ValueError("Base executable bits differ: " + str(source))
        labels = image.get("Config", {}).get("Labels") or {}
        if labels.get("bench.base-sha") != base:
            raise ValueError("Image base label mismatch")
        config = {"repository": str(repository), "output": str(root / "runs" / base), "base_sha": base,
                  "runtime": {"kind": "docker", "image": image["Id"], "python": "python3", "network": "none",
                              "memory": "2g", "cpus": 1, "env": {"PYTHONHASHSEED": "0"}},
                  "production_roots": args.production_root, "test_paths": args.test_path, "pytest_args": [],
                  "worker_root": str(args.scratch_root.resolve() / base), "workers": args.workers,
                  "timeout_seconds": 120, "collection_timeout_seconds": 600, "budget_seconds": None,
                  "raw_events": False}
        inherited_pythonpath = next((e.split("=", 1)[1] for e in image.get("Config", {}).get("Env", []) if e.startswith("PYTHONPATH=")), "")
        if inherited_pythonpath:
            config["runtime"]["env"]["PYTHONPATH"] = inherited_pythonpath
        config_path = root / "configs" / (base + ".json")
        write_json(config_path, config)
        job = {"base_sha": base, "pr_ids": by_base[base], "config": str(config_path),
               "config_sha256": file_hash(config_path), "baseline_lock": lock,
               "image_id": image["Id"], "bundle": str(root / "bundles" / base)}
        if base in reuse:
            job.update(reuse[base])
            write_json(root / "terminals" / (base + ".json"), {**reuse[base], "base_sha": base, "pr_ids": by_base[base]})
        elif base in external:
            job["external_terminal"] = str(Path(external[base]).resolve())
        jobs.append(job)
    plan = {"schema_version": 1, "document_type": "HOST_TRACE_BATCH_PLAN", "created_at": time.time(),
            "scope": scope, "root": str(root), "jobs": jobs, "base_concurrency": args.base_concurrency,
            "workers_per_base": args.workers, "max_test_workers": args.base_concurrency * args.workers,
            "code_files": code_files, "source_metadata": {"path": str(args.retrieval_run / "per-pr.json"),
                "sha256": file_hash(args.retrieval_run / "per-pr.json")},
            "policy": {"selection": "all discovered instances of every selected base, no update labels",
                       "reuse": "verified original bundle, capture provenance retained",
                       "per_test_retries": 0, "new_models": 0, "network": "none"}}
    write_json(root / "plan.json", plan)
    write_status(plan, set())
    print(json.dumps({"plan": str(root / "plan.json"), "prs": len(scope["pull_requests"]), "bases": len(jobs),
                      "reused": len(reuse), "frozen_driver": str(code / "batch_driver.py")}, indent=2))


def check_plan(path):
    plan = read_json(path)
    root = Path(plan["root"])
    for name, checksum in plan["code_files"].items():
        if file_hash(root / "code" / name) != checksum:
            raise ValueError("Frozen execution code changed: " + name)
    for job in plan["jobs"]:
        if file_hash(Path(job["config"])) != job["config_sha256"]:
            raise ValueError("Frozen job configuration changed")
    return plan


def base_view(root, base, evidence):
    index = read_json(evidence / "index.json")
    rows = []
    for entry in index["tests"]:
        target = os.path.relpath(evidence / entry["path"], root / "views")
        rows.append(f'<tr><td><a href="{html.escape(target)}">{html.escape(entry["id"])}</a></td><td>{entry["coverage_status"]}</td><td>{entry["production_function_count"]}</td><td>{entry["edge_count"]}</td></tr>')
    page = '<!doctype html><meta charset="utf-8"><title>Base test traces</title><style>body{font:14px system-ui;margin:24px}td,th{padding:5px;border-bottom:1px solid #ddd;text-align:left}input{width:600px;padding:8px}</style>'
    page += f'<h1>Base {base}</h1><p>Links open complete coverage and call-graph JSON. Unknown coverage is not empty coverage. Use the bundle query.py export command for an HTML/SVG graph.</p><input id="q" placeholder="Filter source test identity"><table><thead><tr><th>Source test</th><th>Coverage status</th><th>Production functions</th><th>Edges</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table><script>q.oninput=()=>{for(const r of document.querySelectorAll("tbody tr"))r.hidden=!r.textContent.toLowerCase().includes(q.value.toLowerCase())}</script>'
    atomic_text(root / "views" / (base + ".html"), page, durable=False)


def write_status(plan, running):
    root = Path(plan["root"])
    rows, mapping = [], {}
    for job in plan["jobs"]:
        base = job["base_sha"]
        terminal = root / "terminals" / (base + ".json")
        row = {"base_sha": base, "pr_ids": job["pr_ids"], "status": "RUNNING" if base in running else "PENDING"}
        if terminal.exists():
            row.update(read_json(terminal))
            if row["status"] in {"SEALED", "SEALED_WITH_GAPS", "REUSED_VERIFIED"}:
                mapping[base] = {"path": str(Path(row["bundle"]) / "manifest.json"), "sha256": row["manifest_sha256"]}
        progress = root / "runs" / base / "progress.json"
        if progress.exists():
            row["progress"] = read_json(progress)
        rows.append(row)
    counts = dict(Counter(r["status"] for r in rows))
    terminal = all(r["status"] not in {"PENDING", "RUNNING"} for r in rows)
    status = {"updated_at": time.time(), "prs": len(plan["scope"]["pull_requests"]), "bases": len(rows),
              "status_counts": counts, "terminal": terminal, "all_bases_sealed": len(mapping) == len(rows),
              "global_worker_limit": plan["max_test_workers"], "jobs": rows}
    atomic_text(root / "status.json", json.dumps(status, ensure_ascii=False, indent=2) + "\n", durable=False)
    atomic_text(root / "dynamic-trace-artifacts.json", json.dumps({"artifacts": mapping}, indent=2) + "\n", durable=False)
    table = []
    for row in rows:
        base = row["base_sha"]
        progress = row.get("progress", {})
        summary = row.get("summary", {})
        count = str(progress.get("completed", summary.get("execution_instances", ""))) + "/" + str(progress.get("expected", summary.get("execution_instances", "")))
        view = "views/" + base + ".html"
        label = f'<a href="{view}">{base[:12]}</a>' if (root / view).exists() else base[:12]
        table.append(f'<tr><td>{label}</td><td>{html.escape(str(row["pr_ids"]))}</td><td>{row["status"]}</td><td>{count}</td><td>{summary.get("covered_production_functions", "")}</td></tr>')
    page = '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="30"><title>98 PR base traces</title><style>body{font:14px system-ui;margin:24px}td,th{padding:6px;border-bottom:1px solid #ddd;text-align:left}</style>'
    page += f'<h1>{status["prs"]} PR / {status["bases"]} base trace collection</h1><p>{html.escape(str(counts))}. Worker limit {plan["max_test_workers"]}. Status is refreshed every 30 seconds. Sealed means execution records and bundle are saved; it does not mean all tests passed.</p><table><tr><th>Base / results</th><th>PR ids</th><th>State</th><th>Recorded / discovered instances</th><th>Unique production functions</th></tr>' + ''.join(table) + '</table>'
    atomic_text(root / "index.html", page, durable=False)
    return status


def one(plan, base):
    job = next(j for j in plan["jobs"] if j["base_sha"] == base)
    root = Path(plan["root"])
    target = root / "terminals" / (base + ".json")
    if target.exists():
        return read_json(target)
    try:
        if job.get("external_terminal"):
            external = Path(job["external_terminal"])
            deadline = time.monotonic() + 86400
            while not external.exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("Existing base job did not reach a terminal state")
                time.sleep(15)
            result = read_json(external)
            if result["base_sha"] != base or result["status"] not in {"SEALED", "REUSED_VERIFIED"}:
                raise ValueError("Existing base job did not produce complete sealed evidence")
            evidence = Path(result["bundle"])
            verified = verify(evidence)
            if read_json(evidence / "manifest.json")["base_sha"] != base:
                raise ValueError("Existing job bundle has another base")
            result = {**result, "status": "REUSED_VERIFIED", "verification": verified,
                      "external_terminal": str(external), "manifest_sha256": file_hash(evidence / "manifest.json")}
            (root / "views").mkdir(exist_ok=True)
            base_view(root, base, evidence)
            write_json(target, result)
            return result
        config = load_config(Path(job["config"]))
        collection = discover(config)
        progress = collect(config)
        destination = Path(job["bundle"])
        if not destination.exists():
            bundle(Path(config["output"]), destination)
        verified = verify(destination)
        result = {"base_sha": base, "pr_ids": job["pr_ids"], "status": "SEALED" if verified["summary"]["dataset_complete"] else "SEALED_WITH_GAPS", "bundle": str(destination),
                  "manifest_sha256": file_hash(destination / "manifest.json"), "summary": verified["summary"],
                  "verification": verified, "collection_errors": collection.get("errors", []),
                  "collection_exit_code": collection["process_exit_code"], "progress": progress}
        (root / "views").mkdir(exist_ok=True)
        base_view(root, base, destination)
        # Keep durable evidence; only discard this job's explicit scratch path
        # after all Worker.close calls have returned.
        if not (Path(config["output"]) / "cleanup-warnings.json").exists():
            _remove_tree(Path(config["worker_root"]))
    except Exception as exc:
        traceback.print_exc()
        result = {"base_sha": base, "pr_ids": job["pr_ids"], "status": "FAILED", "error": str(exc), "finished_at": time.time()}
    write_json(target, result)
    return result


def run(path):
    plan = check_plan(path)
    root = Path(plan["root"])
    preflight = read_json(root / "preflight-summary.json")
    if not preflight["all_passed"] or preflight["plan_sha256"] != file_hash(path):
        raise ValueError("All base environments must pass discovery preflight for this plan before collection")
    with coordinator_lock(root / "supervisor"):
        for job in plan["jobs"]:
            if job.get("status") == "REUSED_VERIFIED":
                (root / "views").mkdir(exist_ok=True)
                base_view(root, job["base_sha"], Path(job["bundle"]))
        pending = [j for j in plan["jobs"] if not (root / "terminals" / (j["base_sha"] + ".json")).exists()]
        def launch(job):
            base = job["base_sha"]
            with (root / "audit" / (base + ".log")).open("ab") as log:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "one", "--plan", str(path), "--base", base], stdout=log, stderr=subprocess.STDOUT)
            if result.returncode and not (root / "terminals" / (base + ".json")).exists():
                write_json(root / "terminals" / (base + ".json"), {"base_sha": base, "pr_ids": job["pr_ids"], "status": "FAILED", "error": f"Coordinator exit {result.returncode}"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=plan["base_concurrency"]) as pool:
            # Submit only active jobs, making RUNNING and PENDING accurate.
            active = {}
            iterator = iter(pending)
            while True:
                while len(active) < plan["base_concurrency"]:
                    job = next(iterator, None)
                    if job is None:
                        break
                    active[pool.submit(launch, job)] = job["base_sha"]
                status = write_status(plan, set(active.values()))
                print(json.dumps({"time": time.time(), "status_counts": status["status_counts"]}), flush=True)
                if not active:
                    break
                done, _ = concurrent.futures.wait(active, timeout=30, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    future.result()
                    del active[future]
        write_json(root / "completion.json", write_status(plan, set()))


def preflight(path):
    plan = check_plan(path)
    root = Path(plan["root"])
    pending = [j for j in plan["jobs"] if j.get("status") != "REUSED_VERIFIED" and not j.get("external_terminal")]
    def probe(job):
        base = job["base_sha"]
        log_path = root / "audit" / (base + "-preflight.log")
        with log_path.open("wb") as log:
            command = [sys.executable, "-m", "test_trace", "discover", "--config", job["config"]]
            rc = subprocess.run(command, cwd=root / "code", stdout=log, stderr=subprocess.STDOUT, timeout=1200).returncode
        collection_path = root / "runs" / base / "collection.json"
        collection = read_json(collection_path) if collection_path.exists() else {}
        result = {"base_sha": base, "returncode": rc, "collection_status": collection.get("collection_status", "unavailable"),
                  "discovered_instances": len(collection.get("items", [])), "errors": collection.get("errors", []),
                  "status": "PASS" if rc == 0 and collection.get("collection_status") == "complete" else "FAIL"}
        write_json(root / "preflight" / (base + ".json"), result)
        print(json.dumps(result), flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=plan["base_concurrency"]) as pool:
        results = list(pool.map(probe, pending))
    summary = {"plan_sha256": file_hash(path), "all_passed": all(r["status"] == "PASS" for r in results),
               "probed_bases": len(results), "reused_or_existing_jobs": len(plan["jobs"]) - len(results),
               "status_counts": dict(Counter(r["status"] for r in results)), "bases": results}
    write_json(root / "preflight-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--retrieval-run", type=Path, required=True)
    prepare_parser.add_argument("--benchmark", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    prepare_parser.add_argument("--scratch-root", type=Path, required=True)
    prepare_parser.add_argument("--image-template", required=True)
    prepare_parser.add_argument("--image-map", type=Path)
    prepare_parser.add_argument("--external-terminal-map", type=Path)
    prepare_parser.add_argument("--production-root", action="append", required=True)
    prepare_parser.add_argument("--test-path", action="append", required=True)
    prepare_parser.add_argument("--reuse-bundle", action="append", type=Path, default=[])
    prepare_parser.add_argument("--base-concurrency", type=int, default=4)
    prepare_parser.add_argument("--workers", type=int, default=16)
    for name in ("run", "one", "preflight"):
        p = commands.add_parser(name)
        p.add_argument("--plan", type=Path, required=True)
        if name == "one":
            p.add_argument("--base", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        if not 1 <= args.workers <= 64 or not 1 <= args.base_concurrency <= 8 or args.base_concurrency * args.workers > 96:
            parser.error("Invalid bounded concurrency")
        prepare(args)
    elif args.command == "run":
        run(args.plan.resolve())
    elif args.command == "preflight":
        preflight(args.plan.resolve())
    else:
        one(check_plan(args.plan), args.base)


if __name__ == "__main__":
    main()
