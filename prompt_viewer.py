"""Dependency-free web viewer for prompt and harness JSON artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "output" / "prompt"
IGNORED_FILES = {"manifest.json"}


def load_json(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    return [payload]


def load_jsonl(path: Path) -> list[Any]:
    items: list[Any] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
    return items


# Extension point for new harness artifact formats.
LOADERS: dict[str, Callable[[Path], list[Any]]] = {
    ".json": load_json,
    ".jsonl": load_jsonl,
}


@dataclass(frozen=True)
class JsonArtifactSource:
    root: Path

    def load(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.root.exists():
            return records
        for path in sorted(item for item in self.root.rglob("*") if item.is_file()):
            if path.name in IGNORED_FILES or path.suffix not in LOADERS:
                continue
            relative_path = str(path.relative_to(self.root))
            for index, data in enumerate(LOADERS[path.suffix](path)):
                records.append(
                    {
                        "id": f"{relative_path}:{index}",
                        "source": relative_path,
                        "data": data,
                    }
                )
        return records


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Prompt & Harness Viewer</title>
  <style>
    :root { font: 15px/1.5 system-ui, sans-serif; color: #172033; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #f5f7fb; }
    header { padding: 16px 20px; background: #172033; color: white; display: flex; gap: 16px; align-items: center; }
    header h1 { margin: 0; font-size: 18px; }
    header span { color: #b9c2d4; }
    button, input { font: inherit; }
    main { display: grid; grid-template-columns: minmax(280px, 34%) 1fr; height: calc(100vh - 60px); }
    aside { overflow: auto; border-right: 1px solid #dce1ea; background: white; }
    .tools { position: sticky; top: 0; display: flex; gap: 8px; padding: 12px; background: white; border-bottom: 1px solid #e5e9f0; }
    #search { flex: 1; min-width: 0; padding: 8px; border: 1px solid #cbd3df; border-radius: 6px; }
    #reload { border: 0; border-radius: 6px; padding: 8px 10px; cursor: pointer; }
    #items { margin: 0; padding: 0; list-style: none; }
    #items button { width: 100%; padding: 11px 14px; border: 0; border-bottom: 1px solid #eef1f5; background: white; text-align: left; cursor: pointer; }
    #items button:hover, #items button.active { background: #edf3ff; }
    .item-title { display: block; font-weight: 650; overflow-wrap: anywhere; }
    .item-source { display: block; margin-top: 3px; color: #687386; font-size: 12px; }
    article { overflow: auto; padding: 24px; }
    .empty { color: #687386; }
    .field { margin-bottom: 18px; }
    .field h2 { margin: 0 0 6px; color: #526078; font-size: 12px; letter-spacing: .05em; text-transform: uppercase; }
    pre { margin: 0; padding: 14px; border: 1px solid #dce1ea; border-radius: 8px; background: white; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.55 ui-monospace, monospace; }
    @media (max-width: 760px) { main { grid-template-columns: 1fr; height: auto; } aside { max-height: 42vh; } article { min-height: 58vh; } }
  </style>
</head>
<body>
  <header><h1>Prompt & Harness Viewer</h1><span id="count">加载中…</span></header>
  <main>
    <aside>
      <div class="tools"><input id="search" placeholder="搜索仓库、PR、文件或内容"><button id="reload">刷新</button></div>
      <ul id="items"></ul>
    </aside>
    <article id="detail"><p class="empty">从左侧选择一条记录。</p></article>
  </main>
  <script>
    let records = [];
    let selectedId = null;
    const list = document.querySelector("#items");
    const detail = document.querySelector("#detail");
    const search = document.querySelector("#search");

    function titleFor(record) {
      const data = record.data || {};
      const identity = [data.repo, data.pr_id && "PR #" + data.pr_id, data.filename].filter(Boolean);
      return identity.join(" · ") || data.name || data.id || record.id;
    }

    function renderList() {
      const query = search.value.trim().toLowerCase();
      const visible = records.filter(record => JSON.stringify(record).toLowerCase().includes(query));
      list.replaceChildren(...visible.map(record => {
        const li = document.createElement("li");
        const button = document.createElement("button");
        button.className = record.id === selectedId ? "active" : "";
        const title = document.createElement("span");
        title.className = "item-title";
        title.textContent = titleFor(record);
        const source = document.createElement("span");
        source.className = "item-source";
        source.textContent = record.source;
        button.append(title, source);
        button.onclick = () => select(record);
        li.append(button);
        return li;
      }));
      document.querySelector("#count").textContent = visible.length + " / " + records.length + " 条记录";
    }

    function select(record) {
      selectedId = record.id;
      const data = record.data && typeof record.data === "object" ? record.data : {value: record.data};
      detail.replaceChildren(...Object.entries(data).map(([name, value]) => {
        const section = document.createElement("section");
        section.className = "field";
        const heading = document.createElement("h2");
        heading.textContent = name;
        const content = document.createElement("pre");
        content.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
        section.append(heading, content);
        return section;
      }));
      renderList();
    }

    async function reload() {
      const response = await fetch("/api/items");
      if (!response.ok) throw new Error("HTTP " + response.status);
      records = (await response.json()).items;
      renderList();
      const selected = records.find(record => record.id === selectedId) || records[0];
      if (selected) select(selected);
      else detail.innerHTML = '<p class="empty">没有找到 JSON/JSONL 记录。</p>';
    }

    function showError(error) { detail.textContent = "加载失败：" + error.message; }
    search.addEventListener("input", renderList);
    document.querySelector("#reload").onclick = () => reload().catch(showError);
    reload().catch(showError);
  </script>
</body>
</html>
"""


def make_handler(source: JsonArtifactSource) -> type[BaseHTTPRequestHandler]:
    class ViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - inherited API
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, "text/html; charset=utf-8", HTML_PAGE.encode())
            elif path == "/api/items":
                self._send_json({"items": source.load()})
            elif path == "/api/health":
                self._send_json({"status": "ok", "record_count": len(source.load())})
            else:
                self._send_json({"error": "not found"}, status=404)

        def _send_json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body)

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ViewerHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="View prompt and harness JSON artifacts")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and count artifacts without starting the server",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = JsonArtifactSource(args.data_dir)
    records = source.load()
    if args.check:
        print(f"Loaded {len(records)} record(s) from {args.data_dir}")
        return

    server = ThreadingHTTPServer((args.host, args.port), make_handler(source))
    host, port = server.server_address[:2]
    print(f"Viewing {len(records)} record(s) at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Viewer stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
