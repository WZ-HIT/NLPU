"""Enrich existing raw PR JSONL with method-level test/focal pairs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from collector.github_client import BASE_URL, GitHubClient
from collector.models import SCHEMA_VERSION
from demo_pipeline import is_test_file
from experiment.ast_extract import extract_changed_definitions
from experiment.pair_tests import pair_changed_tests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT / "output" / "raw_prs"
DEFAULT_CACHE_DIR = Path("/tmp/nlpu-repository-cache")

ProgressCallback = Callable[[str], None]


def _print_progress(message: str) -> None:
    print(message, flush=True)


def _emit_progress(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _run_git(args: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result


class RepositoryCache:
    """Maintain reusable clones and expose detached base/head worktrees."""

    def __init__(self, root: Path, progress: ProgressCallback | None = _print_progress) -> None:
        self.root = root
        self.progress = progress
        self.root.mkdir(parents=True, exist_ok=True)

    def repository_path(self, repo: str) -> Path:
        return self.root / repo.replace("/", "__")

    def ensure_repository(self, repo: str) -> Path:
        path = self.repository_path(repo)
        if not (path / ".git").exists():
            if path.exists():
                raise RuntimeError(f"Repository cache path is not a git clone: {path}")
            _emit_progress(
                self.progress, f"[git] Cloning {repo} into {path} (this can take a while)"
            )
            _run_git(
                [
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    f"https://github.com/{repo}.git",
                    str(path),
                ],
                timeout=600,
            )
            _emit_progress(self.progress, f"[git] Clone ready: {repo}")
        return path

    def ensure_commit(self, repository: Path, sha: str) -> None:
        probe = subprocess.run(
            ["git", "-C", str(repository), "cat-file", "-e", f"{sha}^{{commit}}"],
            text=True,
            capture_output=True,
            check=False,
        )
        if probe.returncode:
            _emit_progress(self.progress, f"[git] Fetching missing commit {sha[:12]}")
            _run_git(
                ["-C", str(repository), "fetch", "--depth=1", "origin", sha],
                timeout=600,
            )
            _emit_progress(self.progress, f"[git] Commit ready: {sha[:12]}")

    @contextmanager
    def checkouts(
        self, repo: str, base_sha: str, head_sha: str
    ) -> Iterator[tuple[Path, Path]]:
        repository = self.ensure_repository(repo)
        self.ensure_commit(repository, base_sha)
        self.ensure_commit(repository, head_sha)
        _emit_progress(
            self.progress,
            f"[git] Preparing worktrees for {repo}: base={base_sha[:12]} head={head_sha[:12]}",
        )
        with tempfile.TemporaryDirectory(prefix="nlpu-checkouts-") as temporary:
            temporary_path = Path(temporary)
            base_root = temporary_path / "base"
            head_root = temporary_path / "head"
            _run_git(
                ["-C", str(repository), "worktree", "add", "--detach", str(base_root), base_sha],
                timeout=300,
            )
            try:
                _run_git(
                    ["-C", str(repository), "worktree", "add", "--detach", str(head_root), head_sha],
                    timeout=300,
                )
                try:
                    yield base_root, head_root
                finally:
                    _run_git(
                        ["-C", str(repository), "worktree", "remove", "--force", str(head_root)]
                    )
            finally:
                _run_git(
                    ["-C", str(repository), "worktree", "remove", "--force", str(base_root)]
                )
                _run_git(["-C", str(repository), "worktree", "prune"])


def _revision_fields_missing(record: dict[str, Any]) -> bool:
    return not record.get("base_sha") or not record.get("head_sha")


def backfill_revision_fields(
    client: GitHubClient, record: dict[str, Any]
) -> dict[str, Any]:
    """Fetch lightweight PR metadata needed to reproduce base/head snapshots."""
    owner, repo = record["repo"].split("/", 1)
    payload, _ = client.get_json(
        f"{BASE_URL}/repos/{owner}/{repo}/pulls/{record['pr_id']}"
    )
    record["head_sha"] = (payload.get("head") or {}).get("sha") or record.get("head_sha", "")
    record["base_sha"] = (payload.get("base") or {}).get("sha") or ""
    record["merge_commit_sha"] = payload.get("merge_commit_sha") or ""
    record["merged_at"] = payload.get("merged_at") or ""
    record["pr_url"] = payload.get("html_url") or ""
    return record


def _candidate_reasons(record: dict[str, Any]) -> list[str]:
    """Return hard blockers for extracting modified pytest cases."""
    reasons: list[str] = []
    if not record.get("merged"):
        reasons.append("PR is not merged")
    if record.get("ci_status") != "success":
        reasons.append("PR head CI is not successful")
    files = record.get("changed_files") or []
    tests = [item for item in files if is_test_file(item.get("filename", ""))]
    if not tests:
        reasons.append("PR has no changed pytest file")
    return reasons


def _coverage_for_record(
    coverage_payload: dict[str, Any], record: dict[str, Any]
) -> dict[str, list[str]]:
    key = f"{record['repo']}#{record['pr_id']}"
    value = coverage_payload.get(key, {})
    return value if isinstance(value, dict) else {}


def enrich_record(
    record: dict[str, Any],
    repository_cache: RepositoryCache,
    *,
    coverage_map: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    reasons = _candidate_reasons(record)
    record["test_changes"] = []
    record["method_test_pairs"] = []
    if reasons:
        record["mining_status"] = "skipped"
        record["mining_reasons"] = reasons
        return record
    if _revision_fields_missing(record):
        record["mining_status"] = "failed"
        record["mining_reasons"] = ["base_sha or head_sha is missing"]
        return record

    try:
        with repository_cache.checkouts(
            record["repo"], record["base_sha"], record["head_sha"]
        ) as (base_root, head_root):
            extracted = extract_changed_definitions(
                base_root, head_root, record.get("changed_files") or []
            )
        pairs = pair_changed_tests(
            record["repo"],
            int(record["pr_id"]),
            extracted["focal_methods"],
            extracted["test_changes"],
            extracted["supporting_definitions"],
            record.get("changed_files") or [],
            coverage_map=coverage_map,
            ci_status=record.get("ci_status", "unknown"),
        )
        record["test_changes"] = extracted["test_changes"]
        record["method_test_pairs"] = pairs
        accepted = [item for item in pairs if item["eligibility"] == "accepted"]
        record["mining_status"] = "mined" if accepted else "no_eligible_pairs"
        record["mining_reasons"] = [
            *(f"{item['file']}: {item['error']}" for item in extracted["errors"]),
            *([] if extracted["focal_methods"] else ["no changed focal method was extracted"]),
            *([] if extracted["test_changes"] else ["no modified pytest case was extracted"]),
            *([] if pairs else ["no modified pytest case could be paired"]),
            *([] if accepted else ["no pair passed focal-reference validation"]),
        ]
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        record["mining_status"] = "failed"
        record["mining_reasons"] = [str(exc)]
    return record


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
    return records


def write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary_path = Path(handle.name)
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary_path.replace(path)


def _update_manifest(raw_dir: Path, summaries: dict[str, dict[str, int]]) -> None:
    path = raw_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"repos": {}}
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["method_mining"] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repos": summaries,
    }
    for file_name, summary in summaries.items():
        repo_key = Path(file_name).stem
        if repo_key in manifest.get("repos", {}):
            manifest["repos"][repo_key].update(summary)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mine_raw_directory(
    raw_dir: Path,
    repository_cache: RepositoryCache,
    *,
    repos: set[str] | None = None,
    pr_keys: set[tuple[str, int]] | None = None,
    client: GitHubClient | None = None,
    backfill_metadata: bool = True,
    coverage_payload: dict[str, Any] | None = None,
    limit: int | None = None,
    progress: ProgressCallback | None = _print_progress,
) -> dict[str, dict[str, int]]:
    summaries: dict[str, dict[str, int]] = {}
    paths = sorted(raw_dir.glob("*.jsonl"))
    selected_total = 0
    for path in paths:
        for record in load_jsonl(path):
            if repos and record.get("repo") not in repos:
                continue
            record_key = (record.get("repo", ""), int(record.get("pr_id", 0)))
            if pr_keys is not None and record_key not in pr_keys:
                continue
            selected_total += 1
    if limit is not None:
        selected_total = min(selected_total, limit)
    _emit_progress(
        progress,
        f"[mine] Selected {selected_total} PR record(s) for method mining",
    )
    processed = 0
    for path in paths:
        records = load_jsonl(path)
        changed = False
        for record in records:
            if repos and record.get("repo") not in repos:
                continue
            record_key = (record.get("repo", ""), int(record.get("pr_id", 0)))
            if pr_keys is not None and record_key not in pr_keys:
                continue
            if limit is not None and processed >= limit:
                continue
            processed += 1
            label = f"{record.get('repo', '?')}#{record.get('pr_id', '?')}"
            _emit_progress(
                progress, f"[mine {processed}/{selected_total}] {label}: starting"
            )
            if backfill_metadata and _revision_fields_missing(record):
                if client is None:
                    raise RuntimeError("A GitHub client is required to backfill revision metadata")
                backfill_revision_fields(client, record)
            enrich_record(
                record,
                repository_cache,
                coverage_map=_coverage_for_record(coverage_payload or {}, record),
            )
            pairs_for_record = record.get("method_test_pairs", [])
            accepted_count = sum(
                item.get("eligibility") == "accepted" for item in pairs_for_record
            )
            status = record.get("mining_status", "unknown")
            message = (
                f"[mine {processed}/{selected_total}] {label}: {status}; "
                f"pairs={len(pairs_for_record)}, accepted={accepted_count}"
            )
            reasons = record.get("mining_reasons") or []
            if reasons and status != "mined":
                message += f"; reason={reasons[0]}"
            _emit_progress(progress, message)
            changed = True
        if changed:
            write_jsonl_atomic(path, records)
        pairs = [pair for record in records for pair in record.get("method_test_pairs", [])]
        summaries[path.name] = {
            "method_pair_count": len(pairs),
            "accepted_pair_count": sum(item.get("eligibility") == "accepted" for item in pairs),
            "mined_pr_count": sum(record.get("mining_status") == "mined" for record in records),
            "mining_failed_pr_count": sum(record.get("mining_status") == "failed" for record in records),
        }
    _update_manifest(raw_dir, summaries)
    return summaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich existing raw PR JSONL with focal-method/test pairs"
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--repo", action="append", help="Only mine this owner/repo")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--coverage-map", type=Path)
    parser.add_argument(
        "--backfill-metadata",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coverage_payload = (
        json.loads(args.coverage_map.read_text(encoding="utf-8"))
        if args.coverage_map
        else {}
    )
    client = GitHubClient(os.getenv("GITHUB_TOKEN", ""))
    summaries = mine_raw_directory(
        args.raw_dir,
        RepositoryCache(args.cache_dir),
        repos=set(args.repo) if args.repo else None,
        client=client,
        backfill_metadata=args.backfill_metadata,
        coverage_payload=coverage_payload,
        limit=args.limit,
    )
    total_pairs = sum(item["method_pair_count"] for item in summaries.values())
    accepted_pairs = sum(item["accepted_pair_count"] for item in summaries.values())
    print(f"Mined {total_pairs} pair(s); {accepted_pairs} accepted for method prompts.")
    for file_name, summary in summaries.items():
        print(f"{file_name}: {summary}")


if __name__ == "__main__":
    main()
