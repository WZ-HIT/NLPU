"""Parallel per-base host analysis; same input, cohorts and exact pair metrics."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import json
from pathlib import Path
import time

from test_trace.common import file_hash, read_json
from experiment.trace_cochange import analyze, aggregate_results, render_report, write_json, VERSION
from experiment.trace_batch_postprocess import independent_check, findings


def worker(arguments):
    base, bundle, retrieval_run, output, permutations = arguments
    result = analyze([Path(bundle)], Path(retrieval_run), Path(output), permutations)
    return base, result


def run(batch, retrieval_run, output, workers=8, permutations=10000):
    if output.exists():
        raise ValueError("Use a new analysis directory")
    output.mkdir(parents=True)
    sources = read_json(batch / "dynamic-trace-artifacts.json")["artifacts"]
    expected = read_json(batch / "plan.json")["scope"]["pull_requests"]
    jobs = []
    for base, source in sorted(sources.items()):
        manifest = Path(source["path"])
        if file_hash(manifest) != source["sha256"]:
            raise ValueError("Batch evidence manifest changed")
        jobs.append((base, str(manifest.parent), str(retrieval_run), str(output / "per-base" / base), permutations))
    finished = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, job) for job in jobs]
        for future in as_completed(futures):
            base, result = future.result()
            finished[base] = result
            write_json(output / "progress.json", {"bases_complete": len(finished), "bases_expected": len(jobs), "updated_at": time.time()})
            print(f"BASE_COMPLETE {len(finished)}/{len(jobs)} {base}", flush=True)
    refs, ledger, inputs, checks, manifests, aggregates = [], {}, {}, {}, {}, []
    for base, summary in sorted(finished.items()):
        prefix = "per-base/" + base + "/"
        for reference in summary["analyses"]:
            reference = {**reference, "path": prefix + reference["path"]}
            refs.append(reference)
            result = read_json(output / reference["path"])
            aggregates.append({k: result[k] for k in ("cohort", "base_sha", "pr_id", "tables")})
        for row in read_json(output / prefix / "base-pr-ledger.json"):
            if row["status"] == "TRACE_AVAILABLE":
                if row["pr_id"] in ledger:
                    raise ValueError("Duplicate PR across base partitions")
                ledger[row["pr_id"]] = row
        for source, checksum in summary["input_source_files"].items():
            if source in inputs and inputs[source] != checksum:
                raise ValueError("Input changed across analysis workers")
            inputs[source] = checksum
        checks.update(summary["trace_verification"])
        manifests.update(summary["input_trace_manifests"])
    if set(ledger) != {r["pr_id"] for r in expected}:
        raise ValueError("Not every selected PR was analyzed")
    rows = [ledger[r["pr_id"]] for r in expected]
    first = next(iter(finished.values()))
    summary = {**{k: v for k, v in first.items() if k not in {"analyses", "aggregate", "input_source_files", "trace_verification", "input_trace_manifests", "missing_bases", "trace_bases", "analyzed_prs"}},
               "version": VERSION, "analyses": sorted(refs, key=lambda r: (r["pr_id"], r["cohort"])),
               "aggregate": aggregate_results(aggregates), "input_source_files": inputs,
               "trace_verification": checks, "input_trace_manifests": manifests,
               "missing_bases": [], "trace_bases": len(finished), "analyzed_prs": len(rows),
               "execution": "exact inverted-index pair statistics, parallel independent base partitions"}
    write_json(output / "summary.json", summary)
    write_json(output / "base-pr-ledger.json", rows)
    with (output / "base-pr-ledger.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pr_id", "base_sha", "updated_methods", "status"], extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    render_report(output, summary, rows)
    write_json(output / "analysis-manifest.json", {"version": VERSION, "files": {
        p.relative_to(output).as_posix(): file_hash(p) for p in output.rglob("*") if p.is_file()},
        "implementation_sha256": file_hash(Path(__file__)), "input_trace_manifests": manifests})
    verification = independent_check(output, retrieval_run)
    write_json(output / "verification.json", verification)
    findings(output, verification)
    write_json(output / "completion.json", {"status": "COMPLETE", "prs": len(rows), "bases": len(finished),
                                            "verification": "PASS", "updated_at": time.time()})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--retrieval-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--permutations", type=int, default=10000)
    args = parser.parse_args()
    run(args.batch.resolve(), args.retrieval_run.resolve(), args.output.resolve(), args.workers, args.permutations)


if __name__ == "__main__":
    main()
