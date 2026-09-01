"""Collector: fetch GitHub PR records and persist them as versioned JSONL.

This package owns the "collection" stage of the NLU pipeline. It is
responsible for turning raw GitHub data into ``PullRequestRecord`` objects
and writing them to ``output/raw_prs/<owner>__<repo>.jsonl`` plus a
``manifest.json`` so downstream consumers (threshold analysis, intent
analysis, dataset building) can read a stable, versioned format.
"""

from .collect import (
    collect_prs,
    iter_records,
    load_records,
    manifest_path,
    raw_prs_dir,
    record_file_path,
)
from .github_client import BASE_URL, GitHubClient, GitHubGraphQLError
from .metadata import CIStatus, PullRequestMetadata, fetch_pr_metadata
from .models import SCHEMA_VERSION, PullRequestRecord

__all__ = [
    "BASE_URL",
    "CIStatus",
    "GitHubClient",
    "GitHubGraphQLError",
    "PullRequestRecord",
    "PullRequestMetadata",
    "SCHEMA_VERSION",
    "collect_prs",
    "fetch_pr_metadata",
    "iter_records",
    "load_records",
    "manifest_path",
    "raw_prs_dir",
    "record_file_path",
]
