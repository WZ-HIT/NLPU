"""Data model for a collected pull request and the output schema version."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PullRequestRecord:
    """A single GitHub pull request as collected by the collector.

    ``changed_files`` holds one dict per changed file with the keys
    ``filename``, ``status``, ``additions``, ``deletions``, ``changes`` and
    ``patch``. The remaining list fields capture natural-language sources and
    issue/PR references that downstream stages consume.
    """

    repo: str
    pr_id: int
    title: str
    body: str
    merged: bool
    ci_status: str
    language: str
    changed_files: list[dict[str, Any]]
    comments: list[str] = field(default_factory=list)
    review_comments: list[str] = field(default_factory=list)
    commit_messages: list[str] = field(default_factory=list)
    commit_issue_refs: list[list[dict[str, Any]]] = field(default_factory=list)
    body_issue_refs: list[dict[str, Any]] = field(default_factory=list)
    closing_issue_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PullRequestRecord":
        """Build a record from a dict, ignoring unknown keys (forward-compatible)."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
