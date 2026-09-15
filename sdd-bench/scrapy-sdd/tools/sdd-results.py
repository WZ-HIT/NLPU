#!/usr/bin/env python3
"""Global SDD experiment result browser and self-contained HTML report builder."""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import webbrowser

VERSION = "1.2.0"
VARIANTS = ("openspec", "speckit", "cc-sdd")
LABEL = {"openspec": "OpenSpec", "speckit": "Spec Kit", "cc-sdd": "cc-sdd"}
ARTIFACT_DIRS = ("outputs", "output-files", "artifacts", "generated-files")
MAX_TEXT = 2 * 1024 * 1024
MAX_DIFF = 20 * 1024 * 1024
MAX_JSONL = 64 * 1024 * 1024


class ViewerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    root: Path
    audit_name: str
    modified: float


@dataclass(frozen=True)
class DatasetReference:
    prompt_record: dict[str, Any]
    prompt_records: tuple[dict[str, Any], ...]
    prompt_source: Path
    pr_record: dict[str, Any] | None
    gold_changes: tuple[dict[str, Any], ...]
    gold_source: Path | None


def bench_default() -> Path:
    return Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_text(path: Path, limit: int = MAX_TEXT) -> str | None:
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        return None
    if b"\0" in data:
        return None
    value = data[:limit].decode("utf-8", errors="replace")
    if size > limit or len(data) > limit:
        value += f"\n\n[Viewer truncated this file after {limit:,} bytes.]\n"
    return value


def is_experiment(path: Path) -> bool:
    if (path / "all-summary.json").is_file():
        return True
    return any(
        (path / variant).is_dir()
        and any((path / variant / item).exists() for item in ("state.json", "summary.json", "failure.json", "phases"))
        for variant in VARIANTS
    )


def discover(bench: Path) -> list[Experiment]:
    log_root = bench / "Log"
    if not log_root.is_dir():
        return []
    log_real = log_root.resolve()
    found: dict[Path, Experiment] = {}
    for parent in log_root.rglob("experiments"):
        if not parent.is_dir():
            continue
        try:
            children = list(parent.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or not is_experiment(child):
                continue
            try:
                real = child.resolve(strict=True)
                real.relative_to(log_real)
                modified = child.stat().st_mtime
            except (OSError, ValueError):
                continue
            found[real] = Experiment(child.name, real, parent.parent.name, modified)
    return sorted(found.values(), key=lambda item: (item.modified, item.experiment_id), reverse=True)


def variant_status(root: Path) -> tuple[str, dict[str, Any]]:
    failure = load_json(root / "failure.json")
    if failure:
        return "FAIL", failure
    summary = load_json(root / "summary.json")
    if summary:
        return str(summary.get("status", "UNKNOWN")), summary
    state = load_json(root / "state.json")
    if state:
        return str(state.get("status", "UNKNOWN")), state
    return "UNKNOWN", {}


def overall_status(exp: Experiment) -> str:
    summary = load_json(exp.root / "all-summary.json")
    if summary and summary.get("status"):
        return str(summary["status"])
    statuses = [variant_status(exp.root / item)[0] for item in VARIANTS if (exp.root / item).is_dir()]
    if not statuses:
        return "UNKNOWN"
    if "FAIL" in statuses or any(item in {"phase_failed", "validation_failed"} for item in statuses):
        return "FAIL"
    if "active" in statuses:
        return "INCOMPLETE"
    if len(set(statuses)) == 1:
        return statuses[0]
    return "MIXED"


def task_id(exp: Experiment) -> str:
    for variant in VARIANTS:
        value = load_json(exp.root / variant / "config.snapshot.json")
        if value and value.get("task_id"):
            return str(value["task_id"])
    return ""


def output_root(bench: Path) -> Path:
    configured = os.environ.get("SDD_RESULTS_OUTPUT_ROOT")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend((bench.parent.parent / "output", bench / "output"))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return candidates[0].resolve()


def experiment_identity(exp: Experiment) -> tuple[str | None, int | None]:
    for variant in VARIANTS:
        value = load_json(exp.root / variant / "config.snapshot.json")
        if not value:
            continue
        sample = value.get("sample_id")
        pr_id = value.get("pr_id")
        return (sample if isinstance(sample, str) else None, pr_id if isinstance(pr_id, int) else None)
    return None, None


def find_prompt_record(root: Path, sample_id: str) -> tuple[dict[str, Any], Path] | None:
    prompt_root = root / "prompt"
    if not prompt_root.is_dir():
        return None
    for source in sorted(prompt_root.glob("*.json")):
        try:
            records = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and record.get("sample_id") == sample_id:
                return record, source
    return None


def find_pr_prompt_records(root: Path, repo: str, pr_id: int) -> tuple[dict[str, Any], ...]:
    prompt_root = root / "prompt"
    if not prompt_root.is_dir():
        return ()
    found: dict[str, dict[str, Any]] = {}
    for source in sorted(prompt_root.glob("*.json")):
        try:
            records = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or record.get("repo") != repo or record.get("pr_id") != pr_id:
                continue
            sample_id = record.get("sample_id")
            if isinstance(sample_id, str):
                found.setdefault(sample_id, record)
    return tuple(found[key] for key in sorted(found))


def find_pr_record(root: Path, record: dict[str, Any], pr_id: int | None) -> tuple[dict[str, Any] | None, Path | None]:
    repo = record.get("repo")
    if not isinstance(repo, str) or "/" not in repo or pr_id is None:
        return None, None
    raw_source = root / "raw_prs" / f"{repo.replace('/', '__')}.jsonl"
    try:
        stream = raw_source.open(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    with stream:
        for line in stream:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict) or raw.get("pr_id") != pr_id:
                continue
            return raw, raw_source
    return None, None


def pr_gold_changes(raw: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
    if not raw:
        return ()
    candidates: list[Any] = []
    changes = raw.get("test_changes")
    if isinstance(changes, list):
        candidates.extend(changes)
    pairs = raw.get("method_test_pairs")
    if isinstance(pairs, list):
        candidates.extend(pair.get("test_change") for pair in pairs if isinstance(pair, dict))
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for change in candidates:
        if not isinstance(change, dict):
            continue
        file_name = change.get("file")
        qualified_name = change.get("qualified_name")
        gold = change.get("gold_test")
        if not isinstance(file_name, str) or not isinstance(qualified_name, str) or not isinstance(gold, str):
            continue
        found.setdefault((file_name, qualified_name), change)
    return tuple(found[key] for key in sorted(found))


def dataset_reference(exp: Experiment, bench: Path) -> DatasetReference | None:
    sample_id, pr_id = experiment_identity(exp)
    if not sample_id:
        return None
    root = output_root(bench)
    located = find_prompt_record(root, sample_id)
    if not located:
        return None
    record, prompt_source = located
    repo = record.get("repo")
    effective_pr = pr_id if pr_id is not None else record.get("pr_id")
    prompt_records = (
        find_pr_prompt_records(root, repo, effective_pr)
        if isinstance(repo, str) and isinstance(effective_pr, int)
        else (record,)
    )
    raw, gold_source = find_pr_record(root, record, effective_pr if isinstance(effective_pr, int) else None)
    return DatasetReference(record, prompt_records or (record,), prompt_source, raw, pr_gold_changes(raw), gold_source)


def stamp(value: float) -> str:
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def resolve(experiments: list[Experiment], selector: str) -> Experiment:
    exact = [item for item in experiments if item.experiment_id == selector]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ViewerError(f"experiment {selector!r} occurs in multiple audit directories")
    matches = [item for item in experiments if item.experiment_id.endswith(selector) or selector in item.experiment_id]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ViewerError(f"no experiment matches {selector!r}")
    raise ViewerError(f"ambiguous selector {selector!r}: " + ", ".join(item.experiment_id for item in matches[:8]))


def choose(experiments: list[Experiment]) -> Experiment:
    if not sys.stdin.isatty():
        raise ViewerError("an experiment id is required when stdin is not interactive")
    print("\nAvailable SDD experiments:\n")
    for number, item in enumerate(experiments, 1):
        present = ", ".join(name for name in VARIANTS if (item.root / name).is_dir()) or "none"
        print(f"  {number:>2}. {item.experiment_id:<32} {overall_status(item):<28} {present}")
    print()
    try:
        number = int(input("Select an experiment number: ").strip())
    except (EOFError, KeyboardInterrupt, ValueError) as error:
        raise ViewerError("no valid experiment selected") from error
    if not 1 <= number <= len(experiments):
        raise ViewerError("experiment number is out of range")
    return experiments[number - 1]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.") or "experiment"


def experiment_token(exp: Experiment) -> str:
    return hashlib.sha256(str(exp.root).encode()).hexdigest()[:20]


def status_class(value: str) -> str:
    upper = value.upper()
    if upper in {"PASS", "FINISHED"}:
        return "pass"
    if upper in {"FAIL", "PHASE_FAILED", "VALIDATION_FAILED"}:
        return "fail"
    if upper in {"AWAITING_MANUAL_REVIEW", "FINISHED_UNVERIFIED", "ACTIVE", "INCOMPLETE"}:
        return "pending"
    return "unknown"


def badge(value: str) -> str:
    return f'<span class="badge {status_class(value)}">{esc(value)}</span>'


def diff_name(block: str, number: int) -> str:
    first = block.splitlines()[0] if block else ""
    match = re.match(r"diff --git a/(.+?) b/(.+)$", first)
    if match:
        return match.group(2)
    for line in block.splitlines():
        if line.startswith("+++ b/"):
            return line[6:]
    return f"diff-{number}"


def split_diff(value: str) -> list[tuple[str, str]]:
    if not value.strip():
        return []
    starts = [match.start() for match in re.finditer(r"(?m)^diff --git ", value)]
    if not starts:
        return [("diff", value)]
    answer = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(value)
        block = value[start:end].rstrip() + "\n"
        answer.append((diff_name(block, index + 1), block))
    return answer


def diff_html(value: str) -> str:
    lines = []
    for line in value.splitlines():
        css = "ctx"
        if line.startswith("+") and not line.startswith("+++"):
            css = "add"
        elif line.startswith("-") and not line.startswith("---"):
            css = "del"
        elif line.startswith("@@"):
            css = "hunk"
        elif line.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file")):
            css = "meta"
        lines.append(f'<span class="line {css}">{esc(line)}</span>')
    return "\n".join(lines)


def diffs(root: Path) -> list[tuple[str, str]]:
    answer: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name in ("git.diff", "git-cached.diff"):
        value = load_text(root / name, MAX_DIFF)
        if not value:
            continue
        for file_name, block in split_diff(value):
            key = (file_name, hashlib.sha256(block.encode()).hexdigest())
            if key not in seen:
                seen.add(key)
                answer.append((file_name, block))
    return answer


def artifacts(root: Path) -> list[tuple[str, str]]:
    answer = []
    seen: set[Path] = set()
    for directory_name in ARTIFACT_DIRS:
        directory = root / directory_name
        if not directory.is_dir():
            continue
        try:
            paths = sorted(path for path in directory.rglob("*") if path.is_file())
        except OSError:
            continue
        for path in paths:
            try:
                real = path.resolve(strict=True)
                real.relative_to(directory.resolve())
            except (OSError, ValueError):
                continue
            if real in seen:
                continue
            value = load_text(path)
            if value is not None:
                seen.add(real)
                answer.append((str(path.relative_to(root)), value))
    for name in ("output-manifest.json", "artifact-manifest.json"):
        value = load_text(root / name)
        if value is not None:
            answer.append((name, value))
    return answer


def agent_messages(path: Path) -> list[str]:
    try:
        if path.stat().st_size > MAX_JSONL:
            return [f"[JSONL exceeds {MAX_JSONL:,} bytes and was not expanded.]"]
        stream = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return []
    answer = []
    with stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "item.completed":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    answer.append(item["text"])
            elif event.get("type") == "error" and isinstance(event.get("message"), str):
                answer.append("ERROR: " + event["message"])
            elif event.get("type") == "turn.failed" and isinstance(event.get("error"), dict):
                message = event["error"].get("message")
                if isinstance(message, str):
                    answer.append("TURN FAILED: " + message)
    return answer


def phase_outputs(root: Path) -> list[tuple[str, list[str]]]:
    directory = root / "phases"
    if not directory.is_dir():
        return []
    answer = []
    for path in sorted(directory.glob("*.jsonl")):
        messages = agent_messages(path)
        if messages:
            answer.append((path.name.removesuffix(".jsonl"), messages))
    return answer


def named_text_files(paths: list[Path], root: Path) -> list[tuple[str, str]]:
    answer = []
    for path in paths:
        value = load_text(path)
        if value and value.strip():
            answer.append((str(path.relative_to(root)), value))
    return answer


def prompts(root: Path) -> list[tuple[str, str]]:
    directory = root / "phases"
    return named_text_files(sorted(directory.glob("*.prompt.md")), root) if directory.is_dir() else []


def logs(root: Path) -> list[tuple[str, str]]:
    paths = [root / "all.stderr.log"]
    for directory, pattern in ((root / "validation", "*.log"), (root / "phases", "*.stderr.log")):
        if directory.is_dir():
            paths.extend(sorted(directory.glob(pattern)))
    return named_text_files(paths, root)


def changed(root: Path) -> list[str]:
    value = load_text(root / "changed-files.txt")
    return [line.rstrip() for line in value.splitlines() if line.strip()] if value else []


def code(value: str, css: str = "") -> str:
    return f'<pre class="code {css}">{esc(value)}</pre>'


def details(title: str, body: str, opened: bool = False) -> str:
    return f'<details class="panel"{" open" if opened else ""}><summary>{esc(title)}</summary>{body}</details>'


def render_variant(name: str, root: Path) -> tuple[str, list[tuple[str, str]]]:
    status, _ = variant_status(root)
    failure = load_json(root / "failure.json") or {}
    state = load_json(root / "state.json") or {}
    summary = load_json(root / "summary.json") or {}
    file_diffs = diffs(root)
    captured = artifacts(root)
    messages = phase_outputs(root)
    prompt_files = prompts(root)
    log_files = logs(root)
    changed_paths = changed(root)
    nav: list[tuple[str, str]] = []
    sections = []
    records = state.get("phase_records") if isinstance(state.get("phase_records"), list) else []
    facts = (
        ("Status", badge(status), True),
        ("Phases", f"{len(records)} recorded", False),
        ("LLM calls", summary.get("llm_call_count", len(records)), False),
        ("Validation", summary.get("validation_status", "not recorded"), False),
        ("Manual review", "required" if summary.get("manual_review_required") else "not recorded", False),
    )
    sections.append('<div class="facts">' + "".join(
        f'<div class="fact"><span>{esc(label)}</span><strong>{value if raw else esc(value)}</strong></div>'
        for label, value, raw in facts
    ) + "</div>")
    if failure:
        sections.append(
            '<section class="failure"><h3>Failure</h3>'
            f'<p><strong>Stage:</strong> {esc(failure.get("failed_stage", "unknown"))} &nbsp; '
            f'<strong>Exit:</strong> {esc(failure.get("exit_code", "unknown"))}</p>'
            f'<pre>{esc(failure.get("reason", "No failure reason was recorded."))}</pre></section>'
        )
    if changed_paths:
        sections.append('<section><h3>Changed files</h3><ul class="file-list">' + "".join(
            f"<li><code>{esc(item)}</code></li>" for item in changed_paths
        ) + "</ul></section>")
    if file_diffs:
        blocks = []
        for number, (file_name, value) in enumerate(file_diffs, 1):
            anchor = f"{name}-diff-{hashlib.sha1(file_name.encode()).hexdigest()[:10]}-{number}"
            nav.append((file_name, anchor))
            blocks.append(f'<article class="diff-file" id="{anchor}"><h4>{esc(file_name)}</h4><pre class="diff">{diff_html(value)}</pre></article>')
        sections.append("<section><h3>Code changes</h3>" + "".join(blocks) + "</section>")
    if captured:
        blocks = []
        for number, (file_name, value) in enumerate(captured, 1):
            anchor = f"{name}-artifact-{hashlib.sha1(file_name.encode()).hexdigest()[:10]}-{number}"
            nav.append((file_name, anchor))
            blocks.append(f'<div id="{anchor}">{details(file_name, code(value))}</div>')
        sections.append("<section><h3>Captured SDD artifacts</h3>" + "".join(blocks) + "</section>")
    if messages:
        sections.append("<section><h3>Agent output</h3>" + "".join(
            details(f"{phase} · {len(items)} Agent message(s)", "".join(f'<div class="agent-message">{code(item)}</div>' for item in items))
            for phase, items in messages
        ) + "</section>")
    if prompt_files:
        sections.append("<section><h3>Prompts</h3>" + "".join(details(name, code(value)) for name, value in prompt_files) + "</section>")
    if log_files:
        sections.append("<section><h3>Logs</h3>" + "".join(details(name, code(value)) for name, value in log_files) + "</section>")
    if len(sections) == 1:
        sections.append('<div class="empty">No additional output was captured for this SDD.</div>')
    header = (
        f'<div class="variant-heading"><div><p class="eyebrow">SDD output</p><h2>{esc(LABEL[name])}</h2></div>{badge(status)}</div>'
        f'<p class="source-path">Source: <code>{esc(root)}</code></p>'
    )
    return header + "".join(sections), nav


def render_overview(exp: Experiment, available: list[str]) -> str:
    rows = []
    for name in available:
        root = exp.root / name
        status, _ = variant_status(root)
        failure = load_json(root / "failure.json") or {}
        summary = load_json(root / "summary.json") or {}
        state = load_json(root / "state.json") or {}
        records = state.get("phase_records") if isinstance(state.get("phase_records"), list) else []
        rows.append(
            "<tr>" + f"<td><strong>{esc(LABEL[name])}</strong></td><td>{badge(status)}</td>"
            f"<td>{len(records)}</td><td>{esc(summary.get('validation_status', '—'))}</td>"
            f"<td>{esc(failure.get('failed_stage', '—'))}</td><td>{esc(failure.get('reason', '—'))}</td></tr>"
        )
    return (
        f'<div class="variant-heading"><div><p class="eyebrow">Experiment overview</p><h2>{esc(exp.experiment_id)}</h2></div>{badge(overall_status(exp))}</div>'
        '<div class="facts">'
        f'<div class="fact"><span>Task</span><strong>{esc(task_id(exp) or "not recorded")}</strong></div>'
        f'<div class="fact"><span>Updated</span><strong>{esc(stamp(exp.modified))}</strong></div>'
        f'<div class="fact"><span>Available SDDs</span><strong>{len(available)}</strong></div></div>'
        '<section><h3>Comparison</h3><div class="table-wrap"><table><thead><tr><th>SDD</th><th>Status</th><th>Phases</th><th>Validation</th><th>Failed stage</th><th>Reason</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div></section>'
        f'<p class="source-path">Experiment source: <code>{esc(exp.root)}</code></p>'
    )


def gold_change_diff(change: dict[str, Any]) -> str:
    file_name = str(change.get("file", "unknown-file"))
    qualified_name = str(change.get("qualified_name", "unknown-test"))
    old_test = change.get("old_test")
    gold_test = change.get("gold_test")
    if not isinstance(old_test, str) or not isinstance(gold_test, str):
        return ""
    return "\n".join(
        difflib.unified_diff(
            old_test.splitlines(),
            gold_test.splitlines(),
            fromfile=f"a/{file_name}::{qualified_name}",
            tofile=f"b/{file_name}::{qualified_name}",
            lineterm="",
        )
    )


def full_pr_patch(reference: DatasetReference) -> tuple[list[str], str]:
    raw = reference.pr_record
    if not raw:
        return [], ""
    names: list[str] = []
    blocks: list[str] = []
    changed_files = raw.get("changed_files")
    if not isinstance(changed_files, list):
        return names, ""
    for changed in changed_files:
        if not isinstance(changed, dict):
            continue
        file_name = changed.get("filename")
        patch = changed.get("patch")
        if not isinstance(file_name, str) or not isinstance(patch, str) or not patch.strip():
            continue
        names.append(file_name)
        blocks.append(
            f"diff --git a/{file_name} b/{file_name}\n"
            f"--- a/{file_name}\n"
            f"+++ b/{file_name}\n{patch.rstrip()}"
        )
    return names, "\n\n".join(blocks)


def pr_context_text(reference: DatasetReference) -> str:
    raw = reference.pr_record
    if not raw:
        return ""
    lines = [
        f"Repository: {raw.get('repo', 'not recorded')}",
        f"PR: {raw.get('pr_id', 'not recorded')}",
        f"URL: {raw.get('pr_url', 'not recorded')}",
        f"Title: {raw.get('title', 'not recorded')}",
        "",
        "Body:",
        str(raw.get("body") or "(empty)"),
    ]
    for heading, key in (
        ("Commit messages", "commit_messages"),
        ("Issue references", "body_issue_refs"),
        ("PR comments", "comments"),
        ("Review comments", "review_comments"),
    ):
        values = raw.get(key)
        if not isinstance(values, list) or not values:
            continue
        lines.extend(("", f"{heading}:"))
        for number, value in enumerate(values, 1):
            lines.append(f"[{number}] {value}")
    changed_files = raw.get("changed_files")
    if isinstance(changed_files, list) and changed_files:
        lines.extend(("", "Changed files:"))
        for changed in changed_files:
            if not isinstance(changed, dict):
                continue
            lines.append(
                f"- {changed.get('filename', 'unknown')} "
                f"({changed.get('status', 'unknown')}; +{changed.get('additions', '?')} "
                f"-{changed.get('deletions', '?')})"
            )
    return "\n".join(lines).rstrip() + "\n"


def render_reference(reference: DatasetReference) -> str:
    record = reference.prompt_record
    facts = (
        ("Repository", record.get("repo", "not recorded")),
        ("PR", record.get("pr_id", "not recorded")),
        ("Selected sample", record.get("sample_id", "not recorded")),
        ("PR samples", len(reference.prompt_records)),
        ("Gold test changes", len(reference.gold_changes)),
    )
    sections = [
        '<div class="variant-heading"><div><p class="eyebrow">PR-level dataset reference</p><h2>PR prompts, gold tests &amp; diffs</h2></div><span class="badge pending">HUMAN ONLY</span></div>',
        '<p class="gold-warning">Gold is loaded only by this host-side viewer. It is not copied into Agent prompts or experiment repositories.</p>',
        '<div class="facts">' + "".join(f'<div class="fact"><span>{esc(name)}</span><strong>{esc(value)}</strong></div>' for name, value in facts) + '</div>',
    ]
    context = pr_context_text(reference)
    if context:
        sections.append('<section><h3>Complete PR context</h3>' + details("Title, body, comments, commits, and changed files", code(context), True) + '</section>')
    prompt_blocks = []
    for prompt_record in reference.prompt_records:
        prompt = prompt_record.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        label = f"{prompt_record.get('sample_id', 'unknown sample')} · {prompt_record.get('old_test_qualified_name', 'unknown test')}"
        prompt_blocks.append(details(label, code(prompt), prompt_record.get("sample_id") == record.get("sample_id")))
    if prompt_blocks:
        sections.append('<section><h3>All dataset prompts for this PR</h3><p class="source-path">Human-only source records; these full generated prompts are not the sanitized Agent input.</p>' + "".join(prompt_blocks) + '</section>')
    gold_blocks = []
    for change in reference.gold_changes:
        file_name = str(change.get("file", "unknown file"))
        qualified_name = str(change.get("qualified_name", "unknown test"))
        old_test = change.get("old_test")
        gold_test = change.get("gold_test")
        difference = gold_change_diff(change)
        content = f'<p class="source-path">File: <code>{esc(file_name)}</code></p>'
        if isinstance(old_test, str) and old_test.strip():
            content += details("Original test", code(old_test))
        if isinstance(gold_test, str) and gold_test.strip():
            content += details("Developer-merged gold test", code(gold_test), True)
        if difference:
            content += details("Gold unified diff", f'<pre class="diff">{diff_html(difference)}</pre>', True)
        gold_blocks.append(details(f"{qualified_name} · {file_name}", content, True))
    if gold_blocks:
        sections.append('<section><h3>All gold tests and gold diffs for this PR</h3>' + "".join(gold_blocks) + '</section>')
    patch_names, patch = full_pr_patch(reference)
    if patch:
        sections.append('<section><h3>Complete developer PR patch</h3><p class="source-path">Files: ' + esc(", ".join(patch_names)) + '</p><pre class="diff">' + diff_html(patch) + '</pre></section>')
    sections.append(f'<p class="source-path">Prompt source: <code>{esc(reference.prompt_source)}</code></p>')
    if reference.gold_source:
        sections.append(f'<p class="source-path">Gold source: <code>{esc(reference.gold_source)}</code></p>')
    return "".join(sections)


def comparison_sources(exp: Experiment, reference: DatasetReference | None) -> list[tuple[str, str, list[str], str]]:
    sources = []
    for variant in VARIANTS:
        root = exp.root / variant
        blocks = diffs(root) if root.is_dir() else []
        if blocks:
            value = "\n".join(block for _, block in blocks)
            sources.append((
                f"source-{variant}",
                f"{LABEL[variant]} code diff",
                [file_name for file_name, _ in blocks],
                value,
            ))
    if reference:
        pr_id = reference.prompt_record.get("pr_id", "unknown")
        context = pr_context_text(reference)
        if context:
            sources.append(("source-pr-context", f"PR {pr_id} complete context", [], context))
        patch_names, patch = full_pr_patch(reference)
        if patch:
            sources.append(("source-pr-full-patch", f"PR {pr_id} complete developer patch", patch_names, patch))
        gold_diffs: list[str] = []
        gold_files: list[str] = []
        originals: list[str] = []
        gold_tests: list[str] = []
        for number, change in enumerate(reference.gold_changes, 1):
            file_name = str(change.get("file", "unknown file"))
            qualified_name = str(change.get("qualified_name", "unknown test"))
            display_file = f"{file_name}::{qualified_name}"
            difference = gold_change_diff(change)
            old_test = change.get("old_test")
            gold_test = change.get("gold_test")
            if difference:
                gold_diffs.append(difference)
                gold_files.append(file_name)
                sources.append((f"source-gold-diff-{number}", f"Gold diff · {qualified_name}", [display_file], difference))
            if isinstance(old_test, str) and old_test.strip():
                originals.append(f"# {display_file}\n\n{old_test.rstrip()}")
            if isinstance(gold_test, str) and gold_test.strip():
                gold_tests.append(f"# {display_file}\n\n{gold_test.rstrip()}")
                sources.append((f"source-gold-test-{number}", f"Gold test · {qualified_name}", [display_file], gold_test))
        if gold_diffs:
            sources.append(("source-pr-gold-diffs", f"PR {pr_id} all gold test diffs", sorted(set(gold_files)), "\n\n".join(gold_diffs)))
        if originals:
            sources.append(("source-pr-original-tests", f"PR {pr_id} all original tests", sorted(set(gold_files)), "\n\n".join(originals)))
        if gold_tests:
            sources.append(("source-pr-gold-tests", f"PR {pr_id} all gold tests", sorted(set(gold_files)), "\n\n".join(gold_tests)))
    return sources


def render_comparison(sources: list[tuple[str, str, list[str], str]]) -> str:
    keys = [key for key, _, _, _ in sources]
    left_key = keys[0]
    right_key = next((key for key in ("source-pr-full-patch", "source-pr-gold-diffs", "source-pr-gold-tests") if key in keys), keys[1])
    files = {key: names for key, _, names, _ in sources}
    values = {key: value for key, _, _, value in sources}

    def options(selected: str) -> str:
        return "".join(
            f'<option value="{esc(key)}"{" selected" if key == selected else ""}>'
            f'{esc(label)} · {esc(", ".join(names))}</option>'
            for key, label, names, _ in sources
        )

    hidden = "".join(
        f'<pre class="compare-source" id="{esc(key)}" data-files="{esc(", ".join(names))}">{esc(value)}</pre>'
        for key, _, names, value in sources
    )
    return (
        '<div class="variant-heading"><div><p class="eyebrow">Side-by-side review</p><h2>Compare outputs</h2></div><span class="badge pending">MANUAL REVIEW</span></div>'
        '<p class="source-path">Choose any two SDD outputs, the complete PR context/patch, or PR-wide and per-test gold sources.</p>'
        '<div class="compare-grid">'
        f'<section class="compare-pane"><select class="compare-select" data-target="compare-left" data-file-target="compare-left-files">{options(left_key)}</select>'
        f'<div class="compare-file" id="compare-left-files">File: {esc(", ".join(files[left_key]))}</div>'
        f'<pre class="compare-code" id="compare-left">{esc(values[left_key])}</pre></section>'
        f'<section class="compare-pane"><select class="compare-select" data-target="compare-right" data-file-target="compare-right-files">{options(right_key)}</select>'
        f'<div class="compare-file" id="compare-right-files">File: {esc(", ".join(files[right_key]))}</div>'
        f'<pre class="compare-code" id="compare-right">{esc(values[right_key])}</pre></section>'
        '</div><div hidden>' + hidden + '</div>'
    )


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDD Results · __TITLE__</title><style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2d;--panel2:#182238;--line:#293754;--text:#e8edf7;--muted:#9eabc2;--blue:#73a7ff;--green:#77d49b;--red:#ff8795;--amber:#f4c76d}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:linear-gradient(145deg,#080d19,#10182a 55%,#0b1221);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}button,a{font:inherit}.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:18px;padding:14px 24px;background:rgba(9,14,27,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}.brand{min-width:max-content;font-weight:800;letter-spacing:.04em}.tabs{display:flex;gap:8px;overflow:auto}.tab-button{color:var(--muted);background:transparent;border:1px solid transparent;border-radius:9px;padding:8px 13px;cursor:pointer}.tab-button:hover,.tab-button.active{color:white;background:var(--panel2);border-color:var(--line)}.layout{display:grid;grid-template-columns:230px minmax(0,1fr);max-width:1600px;margin:0 auto}.sidebar{position:sticky;top:67px;align-self:start;height:calc(100vh - 67px);overflow:auto;padding:24px 16px;border-right:1px solid var(--line)}.sidebar h3{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.12em}.nav-group{display:none}.nav-group.active{display:block}.nav-group a{display:block;color:#cbd6e9;text-decoration:none;padding:7px 8px;border-radius:7px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.nav-group a:hover{color:white;background:var(--panel2)}.content{min-width:0;padding:30px clamp(18px,4vw,60px) 80px}.tab-pane{display:none}.tab-pane.active{display:block}.variant-heading{display:flex;justify-content:space-between;align-items:end;gap:20px}.eyebrow{margin:0 0 3px;color:var(--blue);text-transform:uppercase;letter-spacing:.14em;font-size:11px;font-weight:800}h2{font-size:30px;margin:0}h3{margin:28px 0 12px}h4{margin:0;padding:12px 16px;background:#172136;border-bottom:1px solid var(--line)}.source-path{color:var(--muted);overflow-wrap:anywhere}.badge{display:inline-flex;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:800;letter-spacing:.035em}.badge.pass{color:var(--green);background:#173426}.badge.fail{color:var(--red);background:#3a1921}.badge.pending{color:var(--amber);background:#382e17}.badge.unknown{color:var(--muted);background:#242d40}.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0}.fact{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:13px 15px}.fact span{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}.fact strong{overflow-wrap:anywhere}.failure{background:#2a151c;border:1px solid #6f2b38;border-radius:12px;padding:0 18px 16px}.failure pre{color:#ffd4d9;white-space:pre-wrap}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px}table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em}.file-list{columns:2;padding-left:22px}.file-list li{margin:5px 0;break-inside:avoid}.diff-file{margin:0 0 18px;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#0a0f1b;scroll-margin-top:84px}pre{overflow:auto}.diff,.code{margin:0;padding:16px;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;tab-size:4}.line{display:block;min-height:1.55em;white-space:pre}.line.add{color:#b9f5cb;background:#102b1d}.line.del{color:#ffc0c7;background:#32171e}.line.hunk{color:#a9c9ff;background:#142542}.line.meta{color:#c3b4ff;font-weight:700}details.panel{margin:10px 0;border:1px solid var(--line);border-radius:10px;background:var(--panel);overflow:hidden}details.panel summary{cursor:pointer;padding:11px 14px;font-weight:700;background:var(--panel2)}.agent-message+.agent-message{border-top:1px solid var(--line)}.empty{color:var(--muted);padding:30px;text-align:center;border:1px dashed var(--line);border-radius:12px}.footer{margin-top:50px;color:var(--muted);font-size:12px}.gold-warning{color:#ffe1a3;background:#322817;border:1px solid #705724;border-radius:10px;padding:12px 14px}.compare-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;margin-top:22px}.compare-pane{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.compare-select{width:100%;color:var(--text);background:var(--panel2);border:0;border-bottom:1px solid var(--line);padding:12px 14px;font:inherit;font-weight:700}.compare-file{color:var(--muted);background:#0f1728;border-bottom:1px solid var(--line);padding:8px 14px;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere}.compare-code{height:70vh;min-height:440px;margin:0;padding:16px;overflow:auto;white-space:pre;tab-size:4;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.compare-source{display:none}@media(max-width:850px){.layout{grid-template-columns:1fr}.sidebar{display:none}.topbar{align-items:flex-start;flex-direction:column;gap:8px}.content{padding-top:22px}.file-list{columns:1}.compare-grid{grid-template-columns:1fr}.compare-code{height:52vh}}
</style></head><body><header class="topbar"><div class="brand">SDD Results <small>v__VERSION__</small></div><nav class="tabs">__TABS__</nav></header><div class="layout"><aside class="sidebar">__NAV__</aside><div class="content">__PANES__<div class="footer">Generated __GENERATED__ · Source results were not modified.</div></div></div><script>
const buttons=[...document.querySelectorAll('.tab-button')];function selectTab(name){buttons.forEach(b=>b.classList.toggle('active',b.dataset.tab===name));document.querySelectorAll('.tab-pane').forEach(p=>p.classList.toggle('active',p.id==='tab-'+name));document.querySelectorAll('.nav-group').forEach(n=>n.classList.toggle('active',n.dataset.nav===name));history.replaceState(null,'','#'+name)}buttons.forEach(b=>b.addEventListener('click',()=>selectTab(b.dataset.tab)));const initial=location.hash.slice(1);if(buttons.some(b=>b.dataset.tab===initial))selectTab(initial);document.querySelectorAll('.compare-select').forEach(select=>select.addEventListener('change',()=>{const source=document.getElementById(select.value),target=document.getElementById(select.dataset.target),fileTarget=document.getElementById(select.dataset.fileTarget);if(source&&target)target.textContent=source.textContent;if(source&&fileTarget)fileTarget.textContent='File: '+source.dataset.files}));
</script></body></html>"""


def build_html(exp: Experiment, bench: Path | None = None) -> str:
    bench = bench or bench_default()
    available = [name for name in VARIANTS if (exp.root / name).is_dir()]
    panes = {"overview": render_overview(exp, available)}
    navigation: dict[str, list[tuple[str, str]]] = {"overview": []}
    for name in available:
        panes[name], navigation[name] = render_variant(name, exp.root / name)

    reference = dataset_reference(exp, bench)
    if reference:
        panes["reference"] = render_reference(reference)
        navigation["reference"] = []
    compare = comparison_sources(exp, reference)
    if len(compare) >= 2:
        panes["compare"] = render_comparison(compare)
        navigation["compare"] = []

    tab_labels = {"overview": "Overview", **LABEL, "reference": "PR & Gold", "compare": "Compare"}
    tabs = []
    for name in panes:
        active = " active" if name == "overview" else ""
        tabs.append(f'<button class="tab-button{active}" data-tab="{name}">{esc(tab_labels[name])}</button>')
    pane_html = "".join(
        f'<main class="tab-pane{" active" if name == "overview" else ""}" id="tab-{name}">{value}</main>'
        for name, value in panes.items()
    )
    nav_html = []
    for name, links in navigation.items():
        if links:
            nav_html.append(f'<div class="nav-group" data-nav="{name}"><h3>{esc(tab_labels.get(name, name))} files</h3>' + "".join(
                f'<a href="#{esc(anchor)}">{esc(label)}</a>' for label, anchor in links
            ) + "</div>")
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (PAGE.replace("__TITLE__", esc(exp.experiment_id))
        .replace("__VERSION__", VERSION)
        .replace("__TABS__", "".join(tabs))
        .replace("__NAV__", "".join(nav_html) or '<p class="source-path">No captured files.</p>')
        .replace("__PANES__", pane_html)
        .replace("__GENERATED__", esc(generated)))


def write_report(bench: Path, exp: Experiment, output: Path | None) -> Path:
    destination = (output or bench / "Log" / "reports" / f"{slug(exp.experiment_id)}.html").expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + f".tmp-{os.getpid()}")
    temporary.write_text(build_html(exp, bench), encoding="utf-8")
    temporary.replace(destination)
    return destination



DASHBOARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDD Results Dashboard</title><style>
:root{color-scheme:dark;--panel:#121a2d;--line:#293754;--text:#e8edf7;--muted:#9eabc2;--blue:#73a7ff;--green:#77d49b;--red:#ff8795;--amber:#f4c76d}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#182845 0,#0a0f1d 40%);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}.shell{max-width:1250px;margin:auto;padding:48px 24px 80px}.eyebrow{color:var(--blue);font-size:11px;font-weight:800;letter-spacing:.15em;text-transform:uppercase}h1{font-size:clamp(32px,5vw,54px);line-height:1.05;margin:8px 0 12px}.lead{color:var(--muted);max-width:760px;font-size:17px}.toolbar{display:flex;gap:12px;margin:32px 0 20px}.search{flex:1;min-width:0;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:13px 15px;font:inherit}.refresh{color:var(--text);background:#18243a;border:1px solid var(--line);border-radius:12px;padding:12px 16px;text-decoration:none}.count{color:var(--muted);margin-bottom:12px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(315px,1fr));gap:14px}.card{display:block;color:inherit;text-decoration:none;background:rgba(18,26,45,.9);border:1px solid var(--line);border-radius:14px;padding:18px;transition:.15s transform,.15s border-color}.card:hover{transform:translateY(-2px);border-color:var(--blue)}.card-top{display:flex;align-items:start;justify-content:space-between;gap:12px}.card h2{font-size:18px;margin:0;overflow-wrap:anywhere}.badge{display:inline-flex;padding:4px 9px;border-radius:999px;font-size:11px;font-weight:800;white-space:nowrap}.badge.pass{color:var(--green);background:#173426}.badge.fail{color:var(--red);background:#3a1921}.badge.pending{color:var(--amber);background:#382e17}.badge.unknown{color:var(--muted);background:#242d40}.meta{color:var(--muted);font-size:12px;margin:14px 0 0}.variants{display:flex;gap:6px;flex-wrap:wrap;margin-top:14px}.variant{color:#c9d7ed;background:#1a2740;border-radius:6px;padding:3px 7px;font-size:11px}.empty{color:var(--muted);padding:40px;border:1px dashed var(--line);border-radius:14px;text-align:center}@media(max-width:600px){.shell{padding:30px 16px}.toolbar{flex-direction:column}}
</style></head><body><div class="shell"><p class="eyebrow">Local read-only viewer · v__VERSION__</p><h1>SDD experiment results</h1><p class="lead">Choose an experiment, then switch between OpenSpec, Spec Kit, and cc-sdd to inspect code changes, captured artifacts, Agent output, failures, and review status.</p><div class="toolbar"><input id="search" class="search" type="search" placeholder="Filter by experiment, task, status, or SDD…" autofocus><a class="refresh" href="/">Refresh</a></div><div class="count"><span id="visible">__COUNT__</span> of __COUNT__ experiments</div><div class="grid">__CARDS__</div></div><script>
const cards=[...document.querySelectorAll('.card')],input=document.querySelector('#search'),visible=document.querySelector('#visible');input.addEventListener('input',()=>{const q=input.value.trim().toLowerCase();let n=0;cards.forEach(card=>{const show=!q||card.dataset.search.includes(q);card.style.display=show?'block':'none';if(show)n++});visible.textContent=n});
</script></body></html>"""


def dashboard_html(experiments: list[Experiment]) -> str:
    cards = []
    for exp in experiments:
        status = overall_status(exp)
        present = [name for name in VARIANTS if (exp.root / name).is_dir()]
        searchable = " ".join((exp.experiment_id, task_id(exp), status, *present)).lower()
        chips = "".join(f'<span class="variant">{esc(LABEL[name])}</span>' for name in present)
        cards.append(
            f'<a class="card" data-search="{esc(searchable)}" href="/experiment/{experiment_token(exp)}">'
            f'<div class="card-top"><h2>{esc(exp.experiment_id)}</h2>{badge(status)}</div>'
            f'<p class="meta">Task: {esc(task_id(exp) or "not recorded")}<br>Updated: {esc(stamp(exp.modified))}<br>Audit: {esc(exp.audit_name)}</p>'
            f'<div class="variants">{chips}</div></a>'
        )
    body = "".join(cards) or '<div class="empty">No experiment results were found.</div>'
    return (DASHBOARD.replace("__VERSION__", VERSION)
        .replace("__COUNT__", str(len(experiments)))
        .replace("__CARDS__", body))


def make_server(bench: Path, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"SDDResults/{VERSION}"

        def send_page(self, content: str, status: int = 200) -> None:
            payload = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            request_path = urlparse(self.path).path
            current = discover(bench)
            if request_path == "/":
                self.send_page(dashboard_html(current))
                return
            if request_path == "/healthz":
                payload = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            prefix = "/experiment/"
            if request_path.startswith(prefix):
                token = request_path[len(prefix):]
                matches = [item for item in current if experiment_token(item) == token]
                if len(matches) == 1:
                    page = build_html(matches[0], bench).replace(
                        '<div class="brand">',
                        '<div class="brand"><a href="/" style="color:#9eabc2;text-decoration:none;margin-right:14px">← Experiments</a>',
                        1,
                    )
                    self.send_page(page)
                    return
            self.send_page("<!doctype html><title>Not found</title><h1>404 · Experiment not found</h1><p><a href='/'>Return to dashboard</a></p>", 404)

        def log_message(self, message: str, *args: object) -> None:
            print(f"viewer_request={self.address_string()} {message % args}", file=sys.stderr)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def serve(bench: Path, host: str, port: int, open_browser: bool) -> int:
    try:
        server = make_server(bench, host, port)
    except OSError as error:
        raise ViewerError(f"cannot listen on {host}:{port}: {error}") from error
    actual_host, actual_port = server.server_address[:2]
    browser_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    url = f"http://{browser_host}:{actual_port}/"
    print(f"SDD Results Dashboard v{VERSION}")
    print(f"URL: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nviewer_stopped=true")
    finally:
        server.server_close()
    return 0

def print_list(experiments: list[Experiment]) -> None:
    if not experiments:
        print("No experiments found.")
        return
    header = ("EXPERIMENT", "STATUS", "SDDS", "UPDATED", "TASK")
    rows = []
    for exp in experiments:
        present = ",".join(name for name in VARIANTS if (exp.root / name).is_dir()) or "—"
        rows.append((exp.experiment_id, overall_status(exp), present, stamp(exp.modified), task_id(exp) or "—"))
    widths = [max(len(header[index]), *(len(row[index]) for row in rows)) for index in range(len(header))]
    print("  ".join(header[index].ljust(widths[index]) for index in range(len(header))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(header))))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="sdd-results", description="Discover SDD experiments and build a self-contained HTML viewer.")
    result.add_argument("--bench-root", type=Path, default=bench_default(), help=argparse.SUPPRESS)
    result.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    commands = result.add_subparsers(dest="command")
    commands.add_parser("list", help="list every discovered experiment")
    serve_parser = commands.add_parser("serve", help="start the browser dashboard")
    serve_parser.add_argument("--host", default="127.0.0.1", help="listen address (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8765, help="listen port (default: 8765)")
    serve_parser.add_argument("--open", action="store_true", help="ask the host to open a browser")
    report = commands.add_parser("report", help="generate a standalone HTML report")
    report.add_argument("experiment", nargs="?", help="full or uniquely abbreviated experiment id")
    report.add_argument("--output", "-o", type=Path, help="custom HTML output path")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    bench = args.bench_root.expanduser().resolve()
    experiments = discover(bench)
    if args.command == "list":
        print_list(experiments)
        return 0
    if args.command in {None, "serve"}:
        host = args.host if args.command == "serve" else "127.0.0.1"
        port = args.port if args.command == "serve" else 8765
        open_browser = args.open if args.command == "serve" else False
        return serve(bench, host, port, open_browser)
    if not experiments:
        raise ViewerError(f"no experiment results found beneath {bench / 'Log'}")
    selector = args.experiment if args.command == "report" else None
    exp = resolve(experiments, selector) if selector else choose(experiments)
    output = args.output if args.command == "report" else None
    destination = write_report(bench, exp, output)
    print(f"experiment={exp.experiment_id}")
    print(f"status={overall_status(exp)}")
    print(f"report={destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ViewerError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
