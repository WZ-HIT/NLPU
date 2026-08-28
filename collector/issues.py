"""Issue / PR reference extraction and authoritative closing-issue lookup."""

from __future__ import annotations

import re
from typing import Any

from .github_client import GitHubClient

# Closing keywords recognised by GitHub for auto-linking issues.
# https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue
_CLOSING_KEYWORDS_RE = r"clos(?:e[sd]?|ing)|fix(?:e[sd]|ing)?|resolv(?:e[sd]?|ing)|address(?:e[sd]|ing)?"

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


def extract_issue_refs(text: str, default_repo: str | None = None) -> list[dict[str, Any]]:
    """Extract issue / PR references from ``text``.

    Returns a list of dicts ordered by first appearance and deduplicated by
    ``(external_repo, number)``. Each dict has keys ``number`` (int),
    ``closes`` (bool) and ``external_repo`` (``"owner/repo"`` or ``None``).
    A reference whose ``owner/repo`` equals ``default_repo`` is normalised to
    a same-repo reference (``external_repo=None``).
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


def fetch_closing_issues(
    client: GitHubClient, owner: str, repo: str, pull_number: int
) -> set[tuple[str | None, int]]:
    """Return the canonical set of ``(external_repo, number)`` a PR closes.

    Uses GitHub GraphQL ``closingIssuesReferences``, the authoritative source
    for "which issues will close when this PR merges". Returns an empty set on
    any error so callers can fall back to keyword detection.
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
    try:
        body = client.post_graphql(
            query, {"owner": owner, "name": repo, "number": pull_number}
        )
    except Exception as exc:
        print(
            f"  GraphQL closingIssues lookup failed for PR #{pull_number}: "
            f"{exc}; falling back to keyword detection only"
        )
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
        number = node.get("number")
        if number is None:
            continue
        repo_full = (node.get("repository") or {}).get("nameWithOwner")
        ext = repo_full if repo_full and repo_full.lower() != same_repo else None
        result.add((ext, number))
    return result
