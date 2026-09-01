"""Collection orchestration: fetch PRs and persist them as versioned JSONL."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .github_client import BASE_URL, GitHubClient
from .issues import extract_issue_refs
from .metadata import fetch_pr_metadata
from .models import SCHEMA_VERSION, PullRequestRecord

RAW_DIR_NAME = "raw_prs"
MANIFEST_NAME = "manifest.json"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def raw_prs_dir(output_dir: Path) -> Path:
    return output_dir / RAW_DIR_NAME


def record_file_path(output_dir: Path, owner: str, repo: str) -> Path:
    return raw_prs_dir(output_dir) / f"{owner}__{repo}.jsonl"


def manifest_path(output_dir: Path) -> Path:
    return raw_prs_dir(output_dir) / MANIFEST_NAME


# ---------------------------------------------------------------------------
# Reading existing output
# ---------------------------------------------------------------------------


def iter_records(path: Path) -> Iterator[PullRequestRecord]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield PullRequestRecord.from_dict(json.loads(line))


def load_records(path: Path) -> list[PullRequestRecord]:
    return list(iter_records(path))


def _read_manifest(output_dir: Path) -> dict[str, Any]:
    path = manifest_path(output_dir)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "repos": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(output_dir: Path, manifest: dict[str, Any]) -> None:
    manifest_path(output_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def infer_language(changed_files: list[dict[str, Any]]) -> str:
    for file in changed_files:
        if file["filename"].lower().endswith(".py"):
            return "Python"
    return "Unknown"


def fetch_pull_request_record(
    client: GitHubClient, owner: str, repo: str, pull_number: int
) -> PullRequestRecord:
    pr_url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{pull_number}"
    files_url = f"{pr_url}/files"
    comments_url = f"{BASE_URL}/repos/{owner}/{repo}/issues/{pull_number}/comments"
    review_comments_url = f"{pr_url}/comments"
    commits_url = f"{pr_url}/commits"

    pr_payload, _ = client.get_json(pr_url)
    files_payload = client.paginate(files_url, {"per_page": 100})
    head_sha = pr_payload["head"]["sha"]
    metadata = fetch_pr_metadata(
        client, owner, repo, pull_number, head_sha
    )

    comments_payload = client.paginate(comments_url, {"per_page": 100})
    review_comments_payload = client.paginate(review_comments_url, {"per_page": 100})
    commits_payload = client.paginate(commits_url, {"per_page": 100})

    comments = [item["body"] for item in comments_payload if item.get("body", "").strip()]
    review_comments = [
        item["body"] for item in review_comments_payload if item.get("body", "").strip()
    ]
    commit_messages = [
        item["commit"]["message"]
        for item in commits_payload
        if item.get("commit", {}).get("message", "").strip()
    ]
    commit_issue_refs = [
        extract_issue_refs(msg, default_repo=f"{owner}/{repo}") for msg in commit_messages
    ]
    body_issue_refs = extract_issue_refs(
        pr_payload.get("body") or "", default_repo=f"{owner}/{repo}"
    )

    closing_set = metadata.closing_issues
    if closing_set:
        for ref_list in commit_issue_refs:
            for ref in ref_list:
                if (ref["external_repo"], ref["number"]) in closing_set:
                    ref["closes"] = True
        for ref in body_issue_refs:
            if (ref["external_repo"], ref["number"]) in closing_set:
                ref["closes"] = True
    closing_issue_refs = [
        {"number": number, "external_repo": ext_repo}
        for ext_repo, number in sorted(closing_set, key=lambda item: (item[0] or "", item[1]))
    ]

    changed_files = [
        {
            "filename": item["filename"],
            "status": item["status"],
            "additions": item["additions"],
            "deletions": item["deletions"],
            "changes": item["changes"],
            "patch": item.get("patch", ""),
        }
        for item in files_payload
    ]

    return PullRequestRecord(
        repo=f"{owner}/{repo}",
        pr_id=pr_payload["number"],
        title=pr_payload.get("title", ""),
        body=pr_payload.get("body") or "",
        merged=bool(pr_payload.get("merged_at")),
        ci_status=metadata.ci.status,
        language=infer_language(changed_files),
        changed_files=changed_files,
        comments=comments,
        review_comments=review_comments,
        commit_messages=commit_messages,
        commit_issue_refs=commit_issue_refs,
        body_issue_refs=body_issue_refs,
        closing_issue_refs=closing_issue_refs,
        head_sha=head_sha,
        ci_source=metadata.ci.source,
        ci_rollup_state=metadata.ci.rollup_state,
        ci_check_run_count=metadata.ci.check_run_count,
        ci_status_context_count=metadata.ci.status_context_count,
    )


def _select_merged_prs(
    client: GitHubClient, owner: str, repo: str, limit: int, state: str
) -> list[dict[str, Any]]:
    """Lazily page the PR list, stopping once ``limit`` merged PRs are found."""
    merged_prs: list[dict[str, Any]] = []
    next_url: str | None = f"{BASE_URL}/repos/{owner}/{repo}/pulls"
    next_params: dict[str, Any] | None = {
        "state": state,
        "sort": "updated",
        "direction": "desc",
        "per_page": 100,
    }
    page = 0
    while next_url and len(merged_prs) < limit:
        page += 1
        payload, response_headers = client.get_json(next_url, next_params)
        if not isinstance(payload, list):
            raise RuntimeError(
                f"Expected list payload from {next_url}, got {type(payload).__name__}"
            )
        page_merged = [item for item in payload if item.get("merged_at")]
        merged_prs.extend(page_merged)
        print(
            f"  PR list page {page}: {len(payload)} returned, "
            f"{len(page_merged)} merged (running total: {len(merged_prs)}/{limit})"
        )
        next_url = client.parse_next_link(response_headers.get("Link"))
        next_params = None
        time.sleep(0.2)
    return merged_prs[:limit]


def collect_prs(
    owner: str,
    repo: str,
    limit: int,
    state: str = "closed",
    output_dir: Path | None = None,
    resume: bool = True,
    token: str | None = None,
) -> list[PullRequestRecord]:
    """Collect up to ``limit`` merged PRs and persist them as JSONL.

    Writes one JSON object per PR to ``output/raw_prs/<owner>__<repo>.jsonl``
    and updates ``output/raw_prs/manifest.json``. When ``resume`` is True, PRs
    already present in the file are skipped (incremental / crash-safe). Returns
    the records for the selected PRs (existing + newly fetched).
    """
    token = token or os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN is not set. Please export a GitHub personal access token first."
        )

    output_dir = output_dir or Path("output")
    raw_dir = raw_prs_dir(output_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = record_file_path(output_dir, owner, repo)

    existing = {r.pr_id: r for r in iter_records(path)} if resume else {}
    client = GitHubClient(token)
    selected = _select_merged_prs(client, owner, repo, limit, state)
    selected_numbers = [p["number"] for p in selected]
    to_fetch = [n for n in selected_numbers if n not in existing]

    new_records: list[PullRequestRecord] = []
    mode = "a" if resume else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for index, pull_number in enumerate(to_fetch, start=1):
            print(f"  Fetching PR {pull_number} ({index}/{len(to_fetch)})")
            record = fetch_pull_request_record(client, owner, repo, pull_number)
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
            handle.flush()
            new_records.append(record)

    new_by_id = {r.pr_id: r for r in new_records}
    records = [existing[n] if n in existing else new_by_id[n] for n in selected_numbers]

    manifest = _read_manifest(output_dir)
    repo_key = f"{owner}__{repo}"
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["repos"][repo_key] = {
        "file": f"{repo_key}.jsonl",
        "pr_count": len(records),
        "pr_ids": [r.pr_id for r in records],
        "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _write_manifest(output_dir, manifest)

    already = len(records) - len(new_records)
    print(
        f"[collect] {owner}/{repo}: {len(records)} record(s) total "
        f"({len(new_records)} new, {already} already cached)"
    )
    return records
