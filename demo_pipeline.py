#to do：从PR中筛选出test的部分，搜索对PR分类相关论文。
from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, field
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
API_VERSION = "2022-11-28"
BASE_URL = "https://api.github.com"
TRANSIENT_HTTP_CODES = {500, 502, 503, 504}


@dataclass
class PullRequestRecord:
    repo: str
    pr_id: int
    title: str
    body: str
    merged: bool
    ci_status: str
    language: str
    changed_files: list[dict[str, Any]]
    # Natural language description sources collected from GitHub
    comments: list[str] = field(default_factory=list)         # PR-level discussion comments
    review_comments: list[str] = field(default_factory=list)  # Inline code review comments
    commit_messages: list[str] = field(default_factory=list)  # Commit messages within the PR
    # Issue / PR references parsed from each commit message, parallel to commit_messages.
    # Each inner list holds dicts: {"number": int, "closes": bool, "external_repo": str | None}
    commit_issue_refs: list[list[dict[str, Any]]] = field(default_factory=list)
    # Issue / PR references parsed from the PR body itself (deduplicated, same dict shape).
    body_issue_refs: list[dict[str, Any]] = field(default_factory=list)
    # Authoritative set of issues this PR closes, fetched from GitHub GraphQL
    # (`closingIssuesReferences`). Combines PR body keywords, manual sidebar
    # links, and commit-keyword closes resolved by GitHub itself, so it
    # catches refs the regex misses (e.g. a commit that says "#123" without
    # a closing keyword but whose PR is still officially closing #123).
    # Each item: {"number": int, "external_repo": str | None}
    closing_issue_refs: list[dict[str, Any]] = field(default_factory=list)


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)


def load_sample_prs(path: Path) -> list[PullRequestRecord]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [PullRequestRecord(**item) for item in raw]


def build_github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "nlpu-pr-demo",
        "X-GitHub-Api-Version": API_VERSION,
    }


def github_get_json(url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
    if params:
        url = f"{url}?{urlencode(params)}"

    request = Request(url, headers=headers, method="GET")
    max_attempts = 4

    for attempt in range(1, max_attempts + 1):
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                response_headers = dict(response.headers.items())
                return json.loads(body), response_headers
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in TRANSIENT_HTTP_CODES and attempt < max_attempts:
                wait_seconds = attempt * 2
                print(f"  GitHub API temporary error {exc.code}, retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"GitHub API request failed: {exc.code} {exc.reason} | {error_body}") from exc
        except URLError as exc:
            if attempt < max_attempts:
                wait_seconds = attempt * 2
                print(f"  Network error while calling GitHub API, retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"Network error while calling GitHub API: {exc.reason}") from exc
        except (HTTPException, ConnectionError, TimeoutError) as exc:
            if attempt < max_attempts:
                wait_seconds = attempt * 2
                print(f"  Connection dropped ({type(exc).__name__}), retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"Connection error while calling GitHub API: {exc}") from exc

    raise RuntimeError("GitHub API request failed after retries.")


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None

    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' in section:
            match = re.search(r"<([^>]+)>", section)
            if match:
                return match.group(1)
    return None


def paginate_github(url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    next_url = url
    next_params = params

    while next_url:
        payload, response_headers = github_get_json(next_url, headers, next_params)
        if not isinstance(payload, list):
            raise RuntimeError(f"Expected list payload from {next_url}, got {type(payload).__name__}")
        results.extend(payload)
        next_url = parse_next_link(response_headers.get("Link"))
        next_params = None
        time.sleep(0.2)

    return results


def infer_language(changed_files: list[dict[str, Any]]) -> str:
    for file in changed_files:
        filename = file["filename"].lower()
        if filename.endswith(".py"):
            return "Python"
    return "Unknown"


def fetch_pull_request_record(owner: str, repo: str, pull_number: int, headers: dict[str, str]) -> PullRequestRecord:
    pr_url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{pull_number}"
    files_url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{pull_number}/files"
    comments_url = f"{BASE_URL}/repos/{owner}/{repo}/issues/{pull_number}/comments"
    review_comments_url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{pull_number}/comments"
    commits_url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{pull_number}/commits"

    pr_payload, _ = github_get_json(pr_url, headers)
    files_payload = paginate_github(files_url, headers, {"per_page": 100})
    head_sha = pr_payload["head"]["sha"]
    status_payload, _ = github_get_json(f"{BASE_URL}/repos/{owner}/{repo}/commits/{head_sha}/status", headers)

    # Collect NL description sources: PR-level comments, inline review comments, commit messages
    comments_payload = paginate_github(comments_url, headers, {"per_page": 100})
    review_comments_payload = paginate_github(review_comments_url, headers, {"per_page": 100})
    commits_payload = paginate_github(commits_url, headers, {"per_page": 100})

    comments = [item["body"] for item in comments_payload if item.get("body", "").strip()]
    review_comments = [item["body"] for item in review_comments_payload if item.get("body", "").strip()]
    commit_messages = [
        item["commit"]["message"]
        for item in commits_payload
        if item.get("commit", {}).get("message", "").strip()
    ]
    commit_issue_refs = [
        _extract_issue_refs(msg, default_repo=f"{owner}/{repo}")
        for msg in commit_messages
    ]
    body_issue_refs = _extract_issue_refs(
        pr_payload.get("body") or "", default_repo=f"{owner}/{repo}"
    )

    # Override the regex-based `closes` flag with GitHub's authoritative answer.
    # A commit can reference `#123` without a closing keyword and still close it
    # (e.g. when the PR body or another commit carries the keyword, or when the
    # ref is linked manually). `closingIssuesReferences` is the source of truth.
    closing_set = _fetch_closing_issues_from_github(owner, repo, pull_number, headers)
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
        ci_status=status_payload.get("state", "unknown"),
        language=infer_language(changed_files),
        changed_files=changed_files,
        comments=comments,
        review_comments=review_comments,
        commit_messages=commit_messages,
        commit_issue_refs=commit_issue_refs,
        body_issue_refs=body_issue_refs,
        closing_issue_refs=closing_issue_refs,
    )


def save_raw_records(records: list[PullRequestRecord], path: Path) -> None:
    payload = [
        {
            "repo": record.repo,
            "pr_id": record.pr_id,
            "title": record.title,
            "body": record.body,
            "merged": record.merged,
            "ci_status": record.ci_status,
            "language": record.language,
            "changed_files": record.changed_files,
            "comments": record.comments,
            "review_comments": record.review_comments,
            "commit_messages": record.commit_messages,
            "commit_issue_refs": record.commit_issue_refs,
            "body_issue_refs": record.body_issue_refs,
            "closing_issue_refs": record.closing_issue_refs,
        }
        for record in records
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_pr_data_from_file(source: Path) -> list[PullRequestRecord]:
    prs = load_sample_prs(source)
    print(f"[1/5] Collected {len(prs)} PR records from {source}")
    return prs


def collect_pr_data_from_github(owner: str, repo: str, limit: int, state: str) -> list[PullRequestRecord]:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set. Please export a GitHub personal access token first.")

    headers = build_github_headers(token)
    pulls_url = f"{BASE_URL}/repos/{owner}/{repo}/pulls"

    # Paginate the PR list lazily and stop as soon as `limit` merged PRs are
    # collected. Without this, large repos (pandas has ~57k closed PRs) force
    # the script to walk every page before slicing, which looks like a hang.
    merged_prs: list[dict[str, Any]] = []
    next_url: str | None = pulls_url
    next_params: dict[str, Any] | None = {
        "state": state,
        "sort": "updated",
        "direction": "desc",
        "per_page": 100,
    }
    page = 0
    while next_url and len(merged_prs) < limit:
        page += 1
        payload, response_headers = github_get_json(next_url, headers, next_params)
        if not isinstance(payload, list):
            raise RuntimeError(f"Expected list payload from {next_url}, got {type(payload).__name__}")
        page_merged = [item for item in payload if item.get("merged_at")]
        merged_prs.extend(page_merged)
        print(
            f"  PR list page {page}: {len(payload)} returned, "
            f"{len(page_merged)} merged (running total: {len(merged_prs)}/{limit})"
        )
        next_url = parse_next_link(response_headers.get("Link"))
        next_params = None
        time.sleep(0.2)

    selected = merged_prs[:limit]

    records: list[PullRequestRecord] = []
    for index, pull in enumerate(selected, start=1):
        pr_number = pull["number"]
        print(f"  Fetching PR {pr_number} ({index}/{len(selected)})")
        records.append(fetch_pull_request_record(owner, repo, pr_number, headers))

    ensure_output_dir()
    raw_path = OUTPUT_DIR / f"raw_prs_{owner}_{repo}.json"
    save_raw_records(records, raw_path)
    print(f"[1/5] Collected {len(records)} PR records from GitHub and cached them to {raw_path}")
    return records


def is_code_file(filename: str) -> bool:
    return filename.endswith(".py")


def is_doc_file(filename: str) -> bool:
    lowered = filename.lower()
    return lowered.endswith(".md") or lowered.startswith("docs/") or "/docs/" in lowered


def split_patch_into_hunks(patch: str) -> list[str]:
    if not patch:
        return []

    hunks: list[str] = []
    current: list[str] = []
    for line in patch.splitlines():
        if line.startswith("@@") and current:
            hunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        hunks.append("\n".join(current))
    return hunks


def extract_runnable_parts(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for item in kept:
        pr: PullRequestRecord = item["record"]
        for file in pr.changed_files:
            if not is_code_file(file["filename"]):
                continue
            hunks = split_patch_into_hunks(file.get("patch", ""))
            fragments.append(
                {
                    "repo": pr.repo,
                    "pr_id": pr.pr_id,
                    "filename": file["filename"],
                    "fragment_type": "file",
                    "hunks": hunks,
                    "added_lines": file.get("additions", 0),
                    "deleted_lines": file.get("deletions", 0),
                }
            )
    print(f"[3/5] Extracted {len(fragments)} runnable code fragments")
    return fragments


CHECKLIST_RE = re.compile(r"- \[[ xX]\].*$", re.MULTILINE)
URL_RE = re.compile(r"https?://\S+")
WHITESPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    cleaned = CHECKLIST_RE.sub("", text)
    cleaned = URL_RE.sub("", cleaned)
    cleaned = cleaned.replace("###", " ")
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned


_BOILERPLATE_RE = re.compile(
    r"^\s*(lgtm|looks good to me|ship it|approved|nit[:\s]|no comments?\.?)\s*$",
    re.IGNORECASE,
)


def _is_substantive(text: str) -> bool:
    """Return True when text carries genuine information (≥ 8 words, not pure boilerplate)."""
    stripped = text.strip()
    if not stripped or len(stripped.split()) < 8:
        return False
    return not _BOILERPLATE_RE.match(stripped)


# Stricter test-file detection than `"test" in filename` to avoid false matches
# on names like ``best.py`` or ``latest.py``.
_TEST_PATH_RE = re.compile(r"(^|/)tests?/", re.IGNORECASE)
_TEST_FILENAME_RE = re.compile(r"(^|/)test_[^/]+\.py$|(^|/)[^/]+_test\.py$", re.IGNORECASE)


def _is_test_file(filename: str) -> bool:
    return bool(_TEST_PATH_RE.search(filename) or _TEST_FILENAME_RE.search(filename))


# Closing keywords recognised by GitHub for auto-linking issues.
# https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue
_CLOSING_KEYWORDS_RE = r"clos(?:e[sd]?|ing)|fix(?:e[sd]|ing)?|resolv(?:e[sd]?|ing)|address(?:e[sd]|ing)?"

# Matches issue / PR references in four shapes:
#   1. https://github.com/owner/repo/issues/123 or .../pull/123
#   2. owner/repo#123                              (cross-repo bare)
#   3. GH-123                                      (legacy style used by some projects)
#   4. #123                                        (same-repo, must follow non-word char)
# Optionally preceded by a closing keyword (Fixes / Closes / Resolves / Addresses).
_ISSUE_REF_RE = re.compile(
    rf"""
    (?:(?P<closing>{_CLOSING_KEYWORDS_RE})[\s:]+)?
    (?:
        https?://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/(?:issues|pull)/(?P<url_num>\d+)
      |
        (?P<x_repo>[\w.-]+/[\w.-]+)\#(?P<x_num>\d+)
      |
        (?<![\w/])(?:GH-|\#)(?P<num>\d+)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _extract_issue_refs(text: str, default_repo: str | None = None) -> list[dict[str, Any]]:
    """Extract issue / PR references from a piece of text (commit message, body, comment).

    Returns a list of dicts ordered by first appearance and deduplicated by
    ``(external_repo, number)``. Each dict has keys:

    * ``number``        – issue / PR number (int)
    * ``closes``        – True when the reference is preceded by a closing keyword
    * ``external_repo`` – ``"owner/repo"`` for cross-repo refs, else ``None``

    A reference whose ``owner/repo`` matches ``default_repo`` is normalised to a
    same-repo reference (``external_repo=None``).
    """
    if not text:
        return []

    refs: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int]] = set()

    for match in _ISSUE_REF_RE.finditer(text):
        if match.group("url_num"):
            number = int(match.group("url_num"))
            ext_repo = match.group("url_repo")
        elif match.group("x_num"):
            number = int(match.group("x_num"))
            ext_repo = match.group("x_repo")
        elif match.group("num"):
            number = int(match.group("num"))
            ext_repo = None
        else:
            continue

        if ext_repo and default_repo and ext_repo.lower() == default_repo.lower():
            ext_repo = None

        key = (ext_repo, number)
        if key in seen:
            continue
        seen.add(key)

        refs.append(
            {
                "number": number,
                "closes": match.group("closing") is not None,
                "external_repo": ext_repo,
            }
        )

    return refs


def _fetch_closing_issues_from_github(
    owner: str, repo: str, pull_number: int, headers: dict[str, str]
) -> set[tuple[str | None, int]]:
    """Return the canonical set of (external_repo, number) issues a PR closes.

    Hits GitHub's GraphQL ``closingIssuesReferences`` field, which is the
    authoritative source for "which issues will be closed when this PR
    merges". Cross-repo closes return their full ``owner/repo``;
    same-repo closes return ``external_repo=None``.

    Returns an empty set on any error so callers can keep the regex-based
    closes flag as a graceful fallback.
    """
    query = (
        "query($owner:String!,$name:String!,$number:Int!){"
        " repository(owner:$owner,name:$name){"
        "  pullRequest(number:$number){"
        "   closingIssuesReferences(first:50){"
        "    nodes{ number repository{ nameWithOwner } }"
        "   }"
        "  }"
        " }"
        "}"
    )
    payload = json.dumps(
        {"query": query, "variables": {"owner": owner, "name": repo, "number": pull_number}}
    ).encode("utf-8")
    request = Request(
        f"{BASE_URL}/graphql",
        data=payload,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, HTTPException, ConnectionError, TimeoutError) as exc:
        print(f"  GraphQL closingIssues lookup failed for PR #{pull_number}: {exc}; falling back to keyword detection only")
        return set()

    nodes = (
        ((body.get("data") or {}).get("repository") or {})
        .get("pullRequest", {})
        .get("closingIssuesReferences", {})
        .get("nodes")
        or []
    )
    same_repo = f"{owner}/{repo}".lower()
    result: set[tuple[str | None, int]] = set()
    for node in nodes:
        n = node.get("number")
        if n is None:
            continue
        repo_full = (node.get("repository") or {}).get("nameWithOwner")
        ext = repo_full if repo_full and repo_full.lower() != same_repo else None
        result.add((ext, n))
    return result


def align_descriptions(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aligned: list[dict[str, Any]] = []
    for item in kept:
        pr: PullRequestRecord = item["record"]
        cleaned_title = clean_text(pr.title)
        cleaned_body = clean_text(pr.body)

        # Aggregate substantive comments and commit messages as supplementary NL context
        substantive_comments = [
            clean_text(c) for c in pr.comments + pr.review_comments if _is_substantive(c)
        ]
        substantive_commits = [
            clean_text(m) for m in pr.commit_messages if _is_substantive(m)
        ]

        nl_comments = " | ".join(substantive_comments)
        nl_commits = " | ".join(substantive_commits)

        # Primary description: title + body; extended description adds discussion context
        cleaned_description = f"{cleaned_title}. {cleaned_body}".strip(". ").strip()
        extended_description = " ".join(
            part for part in [cleaned_description, nl_commits, nl_comments] if part
        )

        aligned.append(
            {
                "repo": pr.repo,
                "pr_id": pr.pr_id,
                "nl_title": cleaned_title,
                "nl_body": cleaned_body,
                "nl_comments": nl_comments,
                "nl_commits": nl_commits,
                "nl_description": cleaned_description,
                "nl_description_extended": extended_description,
            }
        )
    print(f"[4/5] Cleaned and aligned {len(aligned)} natural language descriptions")
    return aligned


# ---------------------------------------------------------------------------
# Layer A — hard filter (3 dimensions)
# Layer B — annotations (soft signals, no filtering)
# ---------------------------------------------------------------------------
# to do: 判断是否相关不需过滤，应重新考虑
# to do： 判断相关需重新考虑新方法

# Word-count thresholds derived empirically from 800 merged PRs across
# pandas/requests/django/sklearn (see NL_THRESHOLD_ANALYSIS.md):
# - title >= 4  matches the 25th percentile.
# - body  >= 14 is mu - sigma on the log-normal fit of body_words.
# - commits >= 6 is mu - sigma on commits_words (an alternative when body is short).
_MIN_TITLE_WORDS = 4
_MIN_BODY_WORDS = 14
_MIN_COMMITS_WORDS = 6


def filter_pr(pr: PullRequestRecord) -> tuple[bool, list[str]]:
    """Three-dimension hard filter for NL↔code dataset construction.

    A PR is kept only when *all three* dimensions pass:

    1. **merge_quality**  — merged AND CI green.
    2. **code_presence**  — at least one Python file changed AND not all-docs.
    3. **nl_quality**     — title >= _MIN_TITLE_WORDS AND
                            (body >= _MIN_BODY_WORDS OR commits >= _MIN_COMMITS_WORDS).

    Returns ``(passed, reasons)``. ``reasons`` lists every check that was run,
    prefixed with ``+`` (pass) or ``-`` (fail) for easy debugging.
    """
    reasons: list[str] = []
    passes = 0

    # --- 1. merge_quality ---
    if pr.merged and pr.ci_status == "success":
        reasons.append("+merge_quality: merged and CI green")
        passes += 1
    elif pr.merged:
        reasons.append(f"-merge_quality: merged but CI not green (ci_status={pr.ci_status})")
    else:
        reasons.append("-merge_quality: PR was not merged")

    # --- 2. code_presence ---
    code_files = [f for f in pr.changed_files if is_code_file(f["filename"])]
    all_docs = pr.changed_files and all(is_doc_file(f["filename"]) for f in pr.changed_files)
    if code_files and not all_docs:
        reasons.append(f"+code_presence: {len(code_files)} Python file(s) changed")
        passes += 1
    else:
        reasons.append("-code_presence: no Python source files changed (docs-only or empty)")

    # --- 3. nl_quality ---
    title_words = len(pr.title.split())
    body_words = len(clean_text(pr.body).split())
    commits_words = sum(len(clean_text(m).split()) for m in pr.commit_messages)
    if title_words >= _MIN_TITLE_WORDS and (
        body_words >= _MIN_BODY_WORDS or commits_words >= _MIN_COMMITS_WORDS
    ):
        reasons.append(
            f"+nl_quality: title={title_words} words, body={body_words} words, "
            f"commits={commits_words} words"
        )
        passes += 1
    else:
        reasons.append(
            f"-nl_quality: insufficient description "
            f"(title={title_words}, body={body_words}, commits={commits_words})"
        )

    return passes == 3, reasons


def filter_prs(prs: list[PullRequestRecord]) -> list[dict[str, Any]]:
    """Apply Layer A to every PR; only keep those that pass all three dimensions."""
    kept: list[dict[str, Any]] = []
    for pr in prs:
        passed, reasons = filter_pr(pr)
        if passed:
            kept.append(
                {
                    "repo": pr.repo,
                    "pr_id": pr.pr_id,
                    "filter_reasons": reasons,
                    "record": pr,
                }
            )
    print(f"[2/5] Filtered to {len(kept)} valid PRs (out of {len(prs)})")
    return kept


def annotate_pr(pr: PullRequestRecord) -> dict[str, Any]:
    """Layer B — soft quality signals attached to every kept PR.

    Pure annotation, no filtering. Downstream consumers can sub-select samples
    using these fields without re-running the pipeline.
    """
    title_words = len(pr.title.split())
    body_words = len(clean_text(pr.body).split())
    commits_words = sum(len(clean_text(m).split()) for m in pr.commit_messages)
    return {
        "has_test_changes": any(_is_test_file(f["filename"]) for f in pr.changed_files),
        "closes_issue_count": len(pr.closing_issue_refs),
        "title_words": title_words,
        "body_words": body_words,
        "commits_words": commits_words,
    }


def build_dataset(
    kept: list[dict[str, Any]],
    fragments: list[dict[str, Any]],
    descriptions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    description_index = {(item["repo"], item["pr_id"]): item for item in descriptions}
    kept_index = {(item["repo"], item["pr_id"]): item for item in kept}
    annotation_index = {
        (item["repo"], item["pr_id"]): annotate_pr(item["record"]) for item in kept
    }

    dataset: list[dict[str, Any]] = []
    for fragment in fragments:
        key = (fragment["repo"], fragment["pr_id"])
        description = description_index[key]
        kept_item = kept_index[key]
        dataset.append(
            {
                "repo": fragment["repo"],
                "pr_id": fragment["pr_id"],
                "filename": fragment["filename"],
                "fragment_type": fragment["fragment_type"],
                "filter_reasons": kept_item["filter_reasons"],
                "annotations": annotation_index[key],
                "diff_hunks": fragment["hunks"],
                "nl_title": description["nl_title"],
                "nl_body": description["nl_body"],
                "nl_comments": description["nl_comments"],
                "nl_commits": description["nl_commits"],
                "nl_description": description["nl_description"],
                "nl_description_extended": description["nl_description_extended"],
            }
        )
    print(f"[5/5] Built dataset with {len(dataset)} final samples")
    return dataset


def quality_check(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    empty_text = sum(1 for item in dataset if not item["nl_description"])
    empty_extended = sum(1 for item in dataset if not item["nl_description_extended"])
    empty_hunks = sum(1 for item in dataset if not item["diff_hunks"])
    unique_keys = {(item["repo"], item["pr_id"], item["filename"]) for item in dataset}
    with_test = sum(1 for item in dataset if item["annotations"]["has_test_changes"])
    with_closing = sum(1 for item in dataset if item["annotations"]["closes_issue_count"] > 0)

    return {
        "sample_count": len(dataset),
        "unique_sample_count": len(unique_keys),
        "with_test_changes": with_test,
        "with_closing_issues": with_closing,
        "empty_text_count": empty_text,
        "empty_extended_text_count": empty_extended,
        "empty_hunks_count": empty_hunks,
    }


def write_outputs(dataset: list[dict[str, Any]], report: dict[str, Any]) -> None:
    ensure_output_dir()

    jsonl_path = OUTPUT_DIR / "dataset.jsonl"
    report_path = OUTPUT_DIR / "quality_report.json"

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for item in dataset:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote dataset to {jsonl_path}")
    print(f"Wrote quality report to {report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo pipeline for PR filtering and NL description extraction")
    parser.add_argument(
        "--mode",
        choices=["sample", "github"],
        default="sample",
        help="Use local sample data or fetch real PRs from GitHub",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DATA_DIR / "sample_prs.json",
        help="Path to local sample PR JSON file when mode=sample",
    )
    parser.add_argument("--owner", help="GitHub repo owner when mode=github")
    parser.add_argument("--repo", help="GitHub repo name when mode=github")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of merged PRs to fetch when mode=github",
    )
    parser.add_argument(
        "--state",
        choices=["open", "closed", "all"],
        default="closed",
        help="PR state to query from GitHub before filtering merged PRs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.mode == "github":
        if not args.owner or not args.repo:
            raise RuntimeError("Please provide --owner and --repo when mode=github.")
        prs = collect_pr_data_from_github(args.owner, args.repo, args.limit, args.state)
    else:
        prs = collect_pr_data_from_file(args.source)

    kept = filter_prs(prs)
    fragments = extract_runnable_parts(kept)
    descriptions = align_descriptions(kept)
    dataset = build_dataset(kept, fragments, descriptions)
    report = quality_check(dataset)
    write_outputs(dataset, report)


if __name__ == "__main__":
    main()
