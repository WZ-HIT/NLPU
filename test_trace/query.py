"""Standalone standard-library reader; this file is copied into frozen bundles."""
from __future__ import annotations

import argparse
import collections
import html
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_file(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("Unsafe evidence path")
    target = root / path
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Unsafe evidence path")
    return target


def show(root, identity, max_nodes=200, depth=None):
    if max_nodes < 0 or (depth is not None and depth < 0):
        raise ValueError("Graph limits must be nonnegative")
    index = read(root / "index.json")
    record = next((t for t in index["tests"] if t["id"] == identity), None)
    if record is None:
        record = next((t for t in index["instances"] if t["id"] == identity), None)
    if record is None:
        raise ValueError("Unknown test identity: " + identity)
    if not record.get("path"):
        return {**record, "message": "Execution has not been attempted; coverage is unknown"}
    result = read(safe_file(root, record["path"]))
    if max_nodes == 0 and depth is None:
        return result
    nodes = {n["id"]: n for n in result.get("nodes", [])}
    edges = result.get("edges", [])
    start = result.get("source_test_id", identity)
    graph = collections.defaultdict(list)
    for edge in edges:
        graph[edge["caller"]].append(edge["callee"])
    distances = {start: 0} if start in nodes else {}
    queue = collections.deque(distances)
    while queue:
        current = queue.popleft()
        for target in sorted(graph[current]):
            if target not in distances:
                distances[target] = distances[current] + 1
                queue.append(target)
    ordered = sorted(nodes, key=lambda n: (distances.get(n, float("inf")), n))
    if depth is not None:
        ordered = [n for n in ordered if distances.get(n, float("inf")) <= depth]
    if max_nodes:
        ordered = ordered[:max_nodes]
    kept = set(ordered)
    kept_edges = [e for e in edges if e["caller"] in kept and e["callee"] in kept]
    result["view"] = {"full_node_count": len(nodes), "full_edge_count": len(edges), "shown_node_count": len(kept),
                      "shown_edge_count": len(kept_edges), "depth": depth, "max_nodes": max_nodes,
                      "omitted_nodes": len(nodes) - len(kept), "omitted_edges": len(edges) - len(kept_edges),
                      "disconnected_node_count": len(set(nodes) - set(distances)), "complete_data_preserved_on_disk": True}
    result["nodes"] = [nodes[n] for n in ordered]
    result["edges"] = kept_edges
    # Explicitly distinguish the full coverage set from a bounded graph view.
    result["covered_functions_scope"] = "full_recorded_set"
    return result


def svg(document):
    nodes = document.get("nodes", [])
    edges = document.get("edges", [])
    ids = {n["id"] for n in nodes}
    graph = collections.defaultdict(list)
    for edge in edges:
        graph[edge["caller"]].append(edge["callee"])
    root = document.get("source_test_id")
    distances = {root: 0} if root in ids else {}
    queue = collections.deque(distances)
    while queue:
        current = queue.popleft()
        for child in graph[current]:
            if child not in distances:
                distances[child] = distances[current] + 1
                queue.append(child)
    columns = collections.defaultdict(list)
    unreachable_column = max(distances.values(), default=0) + 1
    for node in nodes:
        columns[distances.get(node["id"], unreachable_column)].append(node)
    positions = {n["id"]: (40 + level * 365, 100 + i * 80) for level, values in columns.items() for i, n in enumerate(values)}
    width = max(600, (max(columns, default=0) + 1) * 365 + 45)
    height = max(180, max((len(v) for v in columns.values()), default=0) * 80 + 100)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#718096"/></marker></defs>',
             '<rect width="100%" height="100%" fill="#f8fafc"/>',
             '<text x="20" y="28" font-size="16" font-family="sans-serif">Observed Python calls — test body only</text>']
    view = document.get("view", {})
    note = f"Showing {len(nodes)} nodes / {len(edges)} edges. Omitted: {view.get('omitted_nodes', 0)} nodes. Disconnected components are retained."
    parts.append('<text x="20" y="54" font-size="12" font-family="sans-serif">' + html.escape(note) + '</text>')
    for edge in edges:
        if edge["caller"] not in positions or edge["callee"] not in positions:
            continue
        x1, y1 = positions[edge["caller"]]
        x2, y2 = positions[edge["callee"]]
        parts.append(f'<path d="M{x1+300},{y1+23} C{x1+340},{y1+23} {x2-40},{y2+23} {x2},{y2+23}" stroke="#94a3b8" fill="none" marker-end="url(#arrow)"/>')
    for node in nodes:
        x, y = positions[node["id"]]
        color = {"production": "#dbeafe", "test": "#dcfce7"}.get(node.get("kind"), "#fef3c7")
        label = node.get("qualified_name", node["id"])
        path = node.get("path", "")
        parts.append(f'<g><title>{html.escape(node["id"])}</title><rect x="{x}" y="{y}" width="300" height="48" rx="7" fill="{color}" stroke="#64748b"/>')
        parts.append(f'<text x="{x+8}" y="{y+20}" font-size="11" font-family="monospace">{html.escape(label[:44])}</text>')
        parts.append(f'<text x="{x+8}" y="{y+37}" font-size="10" font-family="monospace">{html.escape(path[-47:])}</text></g>')
    return "\n".join([*parts, "</svg>"])


def export(root, identity, output, max_nodes=80, depth=None):
    document = show(root, identity, max_nodes, depth)
    image = svg(document)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".svg":
        output.write_text(image, encoding="utf-8")
    elif output.suffix.lower() == ".html":
        info = {k: v for k, v in document.items() if k not in {"nodes", "edges"}}
        output.write_text('<!doctype html><meta charset="utf-8"><title>Test trace</title><style>body{font:14px system-ui;margin:24px;color:#172033} .graph{overflow:auto;max-height:75vh;border:1px solid #ddd} pre{white-space:pre-wrap} button{padding:6px}</style><h1>'
                          + html.escape(identity) + '</h1><p>Full coverage and bounded call-graph view. Setup/teardown excluded. Hover over a node for its identity.</p><label>Zoom <input id="zoom" type="range" min="30" max="180" value="100"></label><div class="graph">'
                          + image + '</div><details><summary>Coverage, provenance and view limits</summary><pre>'
                          + html.escape(json.dumps(info, ensure_ascii=False, indent=2))
                          + '</pre></details><script>document.getElementById("zoom").oninput=function(){document.querySelector("svg").style.zoom=this.value/100}</script>', encoding="utf-8")
    else:
        raise ValueError("Export requires .svg or .html output")
    return {"output": str(output), "view": document.get("view"), "source_test_id": document.get("source_test_id")}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    commands = result.add_subparsers(dest="command", required=True)
    tests = commands.add_parser("tests")
    tests.add_argument("--offset", type=int, default=0)
    tests.add_argument("--limit", type=int, default=50)
    tests.add_argument("--contains", default="")
    for name in ("show", "export"):
        view = commands.add_parser(name)
        view.add_argument("identity")
        view.add_argument("--max-nodes", type=int, default=80 if name == "export" else 200)
        view.add_argument("--depth", type=int)
        if name == "export":
            view.add_argument("--output", required=True, type=Path)
    reverse = commands.add_parser("reverse")
    reverse.add_argument("symbol")
    commands.add_parser("summary")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    root = args.root.resolve()
    if args.command == "tests":
        if args.offset < 0 or not 0 <= args.limit <= 10000:
            raise ValueError("Invalid pagination")
        tests = [t for t in read(root / "index.json")["tests"] if args.contains in t["id"]]
        result = {"total": len(tests), "offset": args.offset, "tests": tests[args.offset:args.offset+args.limit]}
    elif args.command == "show":
        result = show(root, args.identity, args.max_nodes, args.depth)
    elif args.command == "reverse":
        reverse = read(root / "indexes/production-to-tests.json")
        result = {"symbol": args.symbol, "source_test_ids": reverse.get(args.symbol, []), "scope": "validated_passing_instances_only", "absence_does_not_prove_irrelevance": True}
    elif args.command == "export":
        result = export(root, args.identity, args.output, args.max_nodes, args.depth)
    else:
        result = read(root / "index.json")["summary"]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
