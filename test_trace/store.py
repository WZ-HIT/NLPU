"""Aggregate only validated passing instances, preserve unavailable denominators."""
from __future__ import annotations

import collections
import json
import shutil
from pathlib import Path
from typing import Any

from .common import TraceError, atomic_text, digest, file_hash, read_json, safe_relative, write_json


def _derived_json(path: Path, value: Any) -> None:
    # Aggregates and public copies are regenerable from durable instance
    # records. Atomic replacement remains mandatory; per-file journal commits
    # here needlessly serialize thousands of writes on rotating disks.
    atomic_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", durable=False)


def aggregate(root: Path) -> dict[str, Any]:
    run, collection = read_json(root / "run.json"), read_json(root / "collection.json")
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    symbols: dict[str, dict[str, Any]] = {}
    outcomes: collections.Counter = collections.Counter()
    evidence: collections.Counter = collections.Counter()
    instance_index = []
    for item in collection["items"]:
        relative = "instances/" + digest(item["execution_id"]) + ".json"
        path = root / relative
        result = read_json(path) if path.exists() else {"execution_id": item["execution_id"], "source_test_id": item.get("source_test_id"),
                                                      "outcome": "not_run", "evidence_status": "unavailable"}
        outcomes[result["outcome"]] += 1
        evidence[result.get("evidence_status", "unavailable")] += 1
        instance_index.append({"id": item["execution_id"], "source_test_id": item.get("source_test_id"), "path": relative if path.exists() else None,
                               "outcome": result["outcome"], "evidence_status": result.get("evidence_status", "unavailable")})
        if item.get("source_test_id"):
            groups[item["source_test_id"]].append(result)
        if result.get("evidence_status") == "valid":
            if result["outcome"] != "passed":
                raise TraceError("Nonpassing evidence cannot enter the formal graph")
            for node in result.get("nodes", []):
                if node["id"] in symbols and symbols[node["id"]] != node:
                    # Counts belong to edges; a stable symbol must resolve identically.
                    previous = symbols[node["id"]]
                    if any(previous.get(k) != node.get(k) for k in ("path", "qualified_name", "start_line", "kind")):
                        raise TraceError("Inconsistent symbol identity: " + node["id"])
                symbols[node["id"]] = node
    methods = []
    reverse: dict[str, list[str]] = collections.defaultdict(list)
    forward = {}
    for source_id, instances in sorted(groups.items()):
        valid = [r for r in instances if r.get("evidence_status") == "valid"]
        covered, production, node_ids = set(), set(), set()
        edges: dict[tuple, dict[str, Any]] = {}
        boundaries = {}
        for result in valid:
            covered.update(result.get("covered_functions", []))
            production.update(result.get("production_covered_functions", []))
            node_ids.update(n["id"] for n in result.get("nodes", []))
            for edge in result.get("edges", []):
                key = (edge["caller"], edge["callee"], edge.get("kind", "observed_python_parent"))
                if key not in edges:
                    edges[key] = {"caller": key[0], "callee": key[1], "kind": key[2], "count": 0, "supporting_instances": []}
                edges[key]["count"] += edge.get("count", 1)
                edges[key]["supporting_instances"].append(result["execution_id"])
            for boundary in result.get("external_boundaries", []):
                content = {k: v for k, v in boundary.items() if k != "count"}
                key = digest(content)
                if key not in boundaries:
                    boundaries[key] = {**content, "count": 0, "supporting_instances": []}
                boundaries[key]["count"] += boundary.get("count", 1)
                boundaries[key]["supporting_instances"].append(result["execution_id"])
        status = "complete" if len(valid) == len(instances) else "partial" if valid else "unavailable"
        relative = "methods/" + digest(source_id) + ".json"
        document = {"schema_version": 1, "source_test_id": source_id, "collection_scope": "test_body_only", "coverage_status": status,
                    "expected_instances": len(instances), "valid_instances": len(valid),
                    "instances": [{"execution_id": r["execution_id"], "outcome": r["outcome"], "evidence_status": r.get("evidence_status", "unavailable")} for r in instances],
                    "covered_functions": sorted(covered) if valid else None, "production_covered_functions": sorted(production) if valid else None,
                    "nodes": [symbols[i] for i in sorted(node_ids)], "edges": [edges[k] for k in sorted(edges)],
                    "external_boundaries": list(boundaries.values()), "limitations": sorted({x for r in instances for x in r.get("limitations", []) if isinstance(x, str)})}
        _derived_json(root / relative, document)
        methods.append({"id": source_id, "path": relative, "coverage_status": status, "expected_instances": len(instances), "valid_instances": len(valid),
                        "covered_function_count": len(covered) if valid else None, "production_function_count": len(production) if valid else None, "edge_count": len(edges) if valid else None})
        forward[source_id] = sorted(production) if valid else None
        for symbol in production:
            reverse[symbol].append(source_id)
    summary = {"execution_instances": len(collection["items"]), "source_methods": len(methods),
               "unmapped_instances": sum(not i.get("source_test_id") for i in collection["items"]),
               "outcomes": dict(outcomes), "evidence": dict(evidence), "collection_status": collection.get("collection_status"),
               "method_coverage_status": dict(collections.Counter(m["coverage_status"] for m in methods)),
               "covered_project_functions": len(symbols), "covered_production_functions": len(reverse),
               "formal_edges_across_methods": sum(m["edge_count"] or 0 for m in methods),
               "execution_terminal": outcomes.get("not_run", 0) == 0,
               "terminal": outcomes.get("not_run", 0) == 0 and collection.get("collection_status") == "complete",
               "dataset_complete": outcomes.get("not_run", 0) == 0 and collection.get("collection_status") == "complete"}
    index = {"schema_version": 1, "document_type": "TEST_TRACE_INDEX", "snapshot_id": run["snapshot_id"],
             "environment_id": run["environment_id"], "base_sha": run.get("base_sha"), "collection_scope": "test_body_only",
             "summary": summary, "tests": methods, "instances": instance_index, "limitations": run.get("limitations", [])}
    _derived_json(root / "index.json", index)
    _derived_json(root / "symbols.json", symbols)
    _derived_json(root / "indexes/test-to-production.json", forward)
    _derived_json(root / "indexes/production-to-tests.json", dict(sorted(reverse.items())))
    return index


def verify(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise TraceError("No manifest; create a bundle or seal the run first")
    manifest = read_json(manifest_path)
    expected = set(manifest["files"])
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p != manifest_path}
    if actual != expected:
        raise TraceError("Manifest file inventory mismatch")
    if any(p.is_symlink() for p in root.rglob("*")):
        raise TraceError("Bundle may not contain symbolic links")
    for relative, checksum in manifest["files"].items():
        safe_relative(relative)
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()) or file_hash(path) != checksum:
            raise TraceError("Bundle file changed: " + relative)
    index, symbols = read_json(root / "index.json"), read_json(root / "symbols.json")
    if index["snapshot_id"] != manifest["snapshot_id"] or index["environment_id"] != manifest["environment_id"]:
        raise TraceError("Index provenance does not match manifest")
    for item in index["tests"]:
        method = read_json(root / safe_relative(item["path"]))
        covered = method["covered_functions"]
        if method["valid_instances"] == 0 and covered is not None:
            raise TraceError("Unavailable coverage must be null, not empty")
        if covered is not None and not set(covered) <= set(symbols):
            raise TraceError("Covered function has no symbol definition")
        for edge in method["edges"]:
            if edge["caller"] not in symbols or edge["callee"] not in symbols:
                raise TraceError("Graph edge has an undefined endpoint")
    return {"status": "PASS", "files": len(expected), "snapshot_id": manifest["snapshot_id"], "summary": index["summary"]}


def bundle(root: Path, destination: Path) -> dict[str, Any]:
    if destination.resolve().is_relative_to(root.resolve()):
        raise TraceError("Public bundle must be outside the run directory")
    if destination.exists():
        raise TraceError("Bundle destination already exists; frozen evidence is never overwritten")
    index = aggregate(root)
    run = read_json(root / "run.json")
    if not run.get("base_sha"):
        # Generic non-Git projects use snapshot identity; SDD's adapter requires base_sha.
        base = None
    else:
        base = run["base_sha"]
    destination.mkdir(parents=True)
    for name in ("index.json", "symbols.json"):
        shutil.copyfile(root / name, destination / name)
    for name in ("methods", "indexes"):
        if (root / name).exists():
            shutil.copytree(root / name, destination / name)
    (destination / "instances").mkdir()
    for item in index["instances"]:
        if not item["path"]:
            continue
        result = read_json(root / item["path"])
        if result.get("evidence_status") != "valid":
            allowed = {"execution_id", "source_test_id", "outcome", "evidence_status", "collection_scope", "snapshot_id", "environment_id",
                       "duration_seconds", "body_boundary_status", "source_identity_status", "limitations", "reports"}
            result = {k: v for k, v in result.items() if k in allowed}
        result.pop("diagnostic_path", None)
        result.pop("error", None)
        result.pop("raw_events", None)
        result.pop("excluded_sources", None)
        _derived_json(destination / item["path"], result)
    shutil.copyfile(Path(__file__).with_name("query.py"), destination / "query.py")
    atomic_text(destination / "README.md", """# Test-body dynamic evidence

This frozen package contains evidence derived exclusively from the supplied source snapshot.
Coverage is restricted to the actual test body; fixture/setup/teardown/cleanup are excluded.
Only fully passing, attributable instances contribute formal coverage and call graphs.
Unknown/failed/skipped/timeout is not evidence of empty coverage or irrelevance.
Partial method graphs are unions of successful instances and are explicitly labelled.
Only observed Python parent edges are calls. External boundaries and execution ownership
are not synthetic direct calls; disconnected components are retained.
Coverage does not establish that a test needs updating. Search all tests independently.
No diagnostic traces, evaluation labels, target implementation diff or model predictions
are supplied by this package. Runtime limitations are listed in index.json and each result.

Read using Python's standard library only:

    python3 test-traces/query.py --root test-traces tests --offset 0 --limit 50
    python3 test-traces/query.py --root test-traces show 'tests/file.py::Class.test_name'
    python3 test-traces/query.py --root test-traces reverse 'package/file.py::function'

The default show view is bounded. Use --max-nodes 0 for the full recorded graph.
""")
    files = {p.relative_to(destination).as_posix(): file_hash(p) for p in sorted(destination.rglob("*")) if p.is_file()}
    manifest = {"schema_version": 1, "document_type": "TEST_TRACE_BUNDLE", "base_sha": base,
                "snapshot_id": run["snapshot_id"], "environment_id": run["environment_id"],
                "collection_scope": "test_body_only", "source_files": run["source_files"],
                "source_executable_bits": run.get("source_executable_bits", {}),
                "collector_version": run["collector_version"], "collector_files": run["collector_files"],
                "publication_files": {name: file_hash(Path(__file__).with_name(name)) for name in ("store.py", "query.py", "common.py")},
                "files": files, "summary": index["summary"]}
    write_json(destination / "manifest.json", manifest)
    return verify(destination)
