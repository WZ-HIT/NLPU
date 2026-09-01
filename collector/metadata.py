"""Combined PR metadata lookup for closing issues and CI status rollups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .github_client import BASE_URL, GitHubClient, GitHubGraphQLError

PR_METADATA_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 50) {
        nodes {
          number
          repository {
            nameWithOwner
          }
        }
      }
      commits(last: 1) {
        nodes {
          commit {
            oid
            statusCheckRollup {
              state
              contexts(first: 1) {
                checkRunCount
                statusContextCount
              }
            }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class CIStatus:
    status: str
    source: str
    rollup_state: str | None = None
    check_run_count: int = 0
    status_context_count: int = 0


@dataclass(frozen=True)
class PullRequestMetadata:
    head_sha: str
    closing_issues: set[tuple[str | None, int]]
    ci: CIStatus


def normalize_rollup_state(state: str | None) -> str:
    """Map GitHub's StatusCheckRollup state to the collector's CI enum."""
    return {
        "SUCCESS": "success",
        "FAILURE": "failure",
        "ERROR": "failure",
        "PENDING": "pending",
        "EXPECTED": "pending",
    }.get(state or "", "unknown")


def normalize_legacy_state(state: str | None) -> str:
    """Map a legacy combined commit status to the collector's CI enum."""
    lowered = (state or "").lower()
    if lowered == "success":
        return "success"
    if lowered in {"failure", "error"}:
        return "failure"
    if lowered == "pending":
        return "pending"
    return "unknown"


def _parse_closing_issues(
    nodes: list[dict[str, Any]], owner: str, repo: str
) -> set[tuple[str | None, int]]:
    same_repo = f"{owner}/{repo}".lower()
    result: set[tuple[str | None, int]] = set()
    for node in nodes:
        number = node.get("number")
        if number is None:
            continue
        repo_full = (node.get("repository") or {}).get("nameWithOwner")
        external_repo = (
            repo_full if repo_full and repo_full.lower() != same_repo else None
        )
        result.add((external_repo, number))
    return result


def _fetch_graphql_metadata(
    client: GitHubClient,
    owner: str,
    repo: str,
    pull_number: int,
    expected_head_sha: str,
) -> PullRequestMetadata:
    body = client.post_graphql(
        PR_METADATA_QUERY,
        {"owner": owner, "name": repo, "number": pull_number},
    )
    repository = (body.get("data") or {}).get("repository")
    pull_request = repository.get("pullRequest") if repository else None
    if not pull_request:
        raise GitHubGraphQLError(
            f"GraphQL returned no pull request for {owner}/{repo}#{pull_number}"
        )

    closing_nodes = (
        (pull_request.get("closingIssuesReferences") or {}).get("nodes") or []
    )
    commit_nodes = (pull_request.get("commits") or {}).get("nodes") or []
    commit = (commit_nodes[-1] or {}).get("commit") if commit_nodes else None
    if not commit:
        raise GitHubGraphQLError(
            f"GraphQL returned no head commit for {owner}/{repo}#{pull_number}"
        )

    graphql_head_sha = commit.get("oid") or expected_head_sha
    if graphql_head_sha != expected_head_sha:
        raise GitHubGraphQLError(
            f"PR head changed while collecting {owner}/{repo}#{pull_number}"
        )

    rollup = commit.get("statusCheckRollup")
    if rollup:
        contexts = rollup.get("contexts") or {}
        rollup_state = rollup.get("state")
        ci = CIStatus(
            status=normalize_rollup_state(rollup_state),
            source="status_check_rollup",
            rollup_state=rollup_state,
            check_run_count=int(contexts.get("checkRunCount") or 0),
            status_context_count=int(contexts.get("statusContextCount") or 0),
        )
    else:
        ci = CIStatus(status="unknown", source="status_check_rollup")

    return PullRequestMetadata(
        head_sha=expected_head_sha,
        closing_issues=_parse_closing_issues(closing_nodes, owner, repo),
        ci=ci,
    )


def _fetch_legacy_fallback(
    client: GitHubClient,
    owner: str,
    repo: str,
    head_sha: str,
) -> PullRequestMetadata:
    payload, _ = client.get_json(
        f"{BASE_URL}/repos/{owner}/{repo}/commits/{head_sha}/status"
    )
    return PullRequestMetadata(
        head_sha=head_sha,
        closing_issues=set(),
        ci=CIStatus(
            status=normalize_legacy_state(payload.get("state")),
            source="legacy_fallback",
            status_context_count=int(payload.get("total_count") or 0),
        ),
    )


def fetch_pr_metadata(
    client: GitHubClient,
    owner: str,
    repo: str,
    pull_number: int,
    head_sha: str,
) -> PullRequestMetadata:
    """Fetch combined issue/CI metadata, falling back to legacy status on errors."""
    try:
        return _fetch_graphql_metadata(
            client, owner, repo, pull_number, head_sha
        )
    except GitHubGraphQLError as exc:
        print(
            f"  GraphQL metadata lookup failed for PR #{pull_number}: "
            f"{exc}; falling back to legacy commit status"
        )

    try:
        return _fetch_legacy_fallback(client, owner, repo, head_sha)
    except RuntimeError as exc:
        print(
            f"  Legacy status fallback failed for PR #{pull_number}: "
            f"{exc}; storing CI status as unknown"
        )
        return PullRequestMetadata(
            head_sha=head_sha,
            closing_issues=set(),
            ci=CIStatus(status="unknown", source="unavailable"),
        )
