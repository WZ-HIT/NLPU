from __future__ import annotations

import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from collector.github_client import GitHubClient, GitHubGraphQLError
from collector.collect import fetch_pull_request_record
from collector.metadata import (
    CIStatus,
    PullRequestMetadata,
    fetch_pr_metadata,
    normalize_legacy_state,
    normalize_rollup_state,
)
from collector.models import PullRequestRecord, SCHEMA_VERSION


def graphql_payload(
    *,
    state: str | None = "SUCCESS",
    check_runs: int = 3,
    status_contexts: int = 0,
) -> dict:
    rollup = None
    if state is not None:
        rollup = {
            "state": state,
            "contexts": {
                "checkRunCount": check_runs,
                "statusContextCount": status_contexts,
            },
        }
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "closingIssuesReferences": {
                        "nodes": [
                            {
                                "number": 10,
                                "repository": {"nameWithOwner": "acme/widgets"},
                            },
                            {
                                "number": 20,
                                "repository": {"nameWithOwner": "other/project"},
                            },
                        ]
                    },
                    "commits": {
                        "nodes": [
                            {
                                "commit": {
                                    "oid": "abc123",
                                    "statusCheckRollup": rollup,
                                }
                            }
                        ]
                    },
                }
            }
        }
    }


class MetadataTests(unittest.TestCase):
    def test_rollup_state_mapping(self) -> None:
        expected = {
            "SUCCESS": "success",
            "FAILURE": "failure",
            "ERROR": "failure",
            "PENDING": "pending",
            "EXPECTED": "pending",
            None: "unknown",
            "NEW_STATE": "unknown",
        }
        for state, result in expected.items():
            with self.subTest(state=state):
                self.assertEqual(normalize_rollup_state(state), result)

    def test_legacy_state_mapping(self) -> None:
        expected = {
            "success": "success",
            "failure": "failure",
            "error": "failure",
            "pending": "pending",
            None: "unknown",
        }
        for state, result in expected.items():
            with self.subTest(state=state):
                self.assertEqual(normalize_legacy_state(state), result)

    def test_fetches_combined_rollup_and_closing_issues(self) -> None:
        client = Mock()
        client.post_graphql.return_value = graphql_payload()

        metadata = fetch_pr_metadata(
            client, "acme", "widgets", pull_number=7, head_sha="abc123"
        )

        self.assertEqual(metadata.head_sha, "abc123")
        self.assertEqual(metadata.ci.status, "success")
        self.assertEqual(metadata.ci.source, "status_check_rollup")
        self.assertEqual(metadata.ci.check_run_count, 3)
        self.assertEqual(metadata.ci.status_context_count, 0)
        self.assertEqual(
            metadata.closing_issues,
            {(None, 10), ("other/project", 20)},
        )
        client.get_json.assert_not_called()

    def test_null_rollup_is_unknown_without_legacy_fallback(self) -> None:
        client = Mock()
        client.post_graphql.return_value = graphql_payload(state=None)

        metadata = fetch_pr_metadata(
            client, "acme", "widgets", pull_number=7, head_sha="abc123"
        )

        self.assertEqual(metadata.ci.status, "unknown")
        self.assertEqual(metadata.ci.source, "status_check_rollup")
        client.get_json.assert_not_called()

    def test_graphql_error_falls_back_to_legacy_status(self) -> None:
        client = Mock()
        client.post_graphql.side_effect = GitHubGraphQLError("temporary failure")
        client.get_json.return_value = (
            {"state": "success", "total_count": 2},
            {},
        )

        metadata = fetch_pr_metadata(
            client, "acme", "widgets", pull_number=7, head_sha="abc123"
        )

        self.assertEqual(metadata.ci.status, "success")
        self.assertEqual(metadata.ci.source, "legacy_fallback")
        self.assertEqual(metadata.ci.status_context_count, 2)
        self.assertEqual(metadata.closing_issues, set())

    def test_both_sources_failing_produces_unknown(self) -> None:
        client = Mock()
        client.post_graphql.side_effect = GitHubGraphQLError("graphql down")
        client.get_json.side_effect = RuntimeError("rest down")

        metadata = fetch_pr_metadata(
            client, "acme", "widgets", pull_number=7, head_sha="abc123"
        )

        self.assertEqual(metadata.ci.status, "unknown")
        self.assertEqual(metadata.ci.source, "unavailable")


class CollectorIntegrationTests(unittest.TestCase):
    def test_record_uses_rollup_metadata_fields(self) -> None:
        client = Mock()
        client.get_json.return_value = (
            {
                "number": 7,
                "title": "Improve widget behavior",
                "body": "Fixes #10 with enough implementation detail.",
                "merged_at": "2026-08-01T00:00:00Z",
                "head": {"sha": "abc123"},
            },
            {},
        )

        def paginate(url: str, params: dict) -> list[dict]:
            if url.endswith("/files"):
                return [
                    {
                        "filename": "widgets/core.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 1,
                        "changes": 4,
                        "patch": "@@ -1 +1 @@",
                    }
                ]
            if url.endswith("/commits"):
                return [{"commit": {"message": "Improve widget behavior"}}]
            return []

        client.paginate.side_effect = paginate
        metadata = PullRequestMetadata(
            head_sha="abc123",
            closing_issues={(None, 10)},
            ci=CIStatus(
                status="success",
                source="status_check_rollup",
                rollup_state="SUCCESS",
                check_run_count=8,
                status_context_count=1,
            ),
        )

        with patch(
            "collector.collect.fetch_pr_metadata",
            return_value=metadata,
        ) as fetch_metadata:
            record = fetch_pull_request_record(
                client, "acme", "widgets", pull_number=7
            )

        self.assertEqual(record.ci_status, "success")
        self.assertEqual(record.ci_source, "status_check_rollup")
        self.assertEqual(record.ci_rollup_state, "SUCCESS")
        self.assertEqual(record.ci_check_run_count, 8)
        self.assertEqual(record.ci_status_context_count, 1)
        self.assertEqual(record.head_sha, "abc123")
        self.assertEqual(record.closing_issue_refs, [{"number": 10, "external_repo": None}])
        fetch_metadata.assert_called_once_with(
            client, "acme", "widgets", 7, "abc123"
        )
        client.get_json.assert_called_once()

class ModelCompatibilityTests(unittest.TestCase):
    def test_schema_v1_record_loads_with_v2_defaults(self) -> None:
        old_record = {
            "repo": "acme/widgets",
            "pr_id": 7,
            "title": "Improve widget behavior",
            "body": "Details",
            "merged": True,
            "ci_status": "success",
            "language": "Python",
            "changed_files": [],
            "unknown_future_field": "ignored",
        }

        record = PullRequestRecord.from_dict(old_record)

        self.assertEqual(SCHEMA_VERSION, 2)
        self.assertEqual(record.head_sha, "")
        self.assertEqual(record.ci_source, "legacy")
        self.assertIsNone(record.ci_rollup_state)
        self.assertEqual(record.ci_check_run_count, 0)
        self.assertEqual(record.ci_status_context_count, 0)


class FakeResponse:
    def __init__(self, payload: dict | str) -> None:
        self.payload = (
            json.dumps(payload).encode()
            if isinstance(payload, dict)
            else payload.encode()
        )

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class GitHubGraphQLClientTests(unittest.TestCase):
    @patch("collector.github_client.urlopen")
    def test_retries_transient_http_error(self, mocked_urlopen: Mock) -> None:
        error = HTTPError(
            "https://api.github.com/graphql",
            503,
            "Unavailable",
            {},
            io.BytesIO(b'{"message":"try later"}'),
        )
        mocked_urlopen.side_effect = [
            error,
            FakeResponse({"data": {"viewer": {"login": "octocat"}}}),
        ]
        client = GitHubClient("token")

        with patch.object(client, "_backoff") as backoff:
            body = client.post_graphql("query { viewer { login } }", {})

        self.assertEqual(body["data"]["viewer"]["login"], "octocat")
        self.assertEqual(mocked_urlopen.call_count, 2)
        backoff.assert_called_once()

    @patch("collector.github_client.urlopen")
    def test_raises_for_graphql_errors(self, mocked_urlopen: Mock) -> None:
        mocked_urlopen.return_value = FakeResponse(
            {"errors": [{"message": "Field is unavailable"}]}
        )
        client = GitHubClient("token")

        with self.assertRaisesRegex(GitHubGraphQLError, "Field is unavailable"):
            client.post_graphql("query { missing }", {})

    @patch("collector.github_client.urlopen")
    def test_raises_for_invalid_json(self, mocked_urlopen: Mock) -> None:
        mocked_urlopen.return_value = FakeResponse("not-json")
        client = GitHubClient("token")

        with self.assertRaisesRegex(GitHubGraphQLError, "Invalid JSON"):
            client.post_graphql("query { viewer { login } }", {})


if __name__ == "__main__":
    unittest.main()
