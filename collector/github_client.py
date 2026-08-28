"""Thin GitHub REST + GraphQL client with retry and pagination helpers."""

from __future__ import annotations

import json
import re
import time
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_VERSION = "2022-11-28"
BASE_URL = "https://api.github.com"
TRANSIENT_HTTP_CODES = {500, 502, 503, 504}
_MAX_ATTEMPTS = 4


class GitHubClient:
    """Minimal GitHub API client used by the collector.

    Wraps the stdlib ``urllib`` stack so the rest of the package does not
    depend on any third-party HTTP library. Supports GET with retry/backoff,
    Link-header pagination, and GraphQL POST.
    """

    def __init__(self, token: str, base_url: str = BASE_URL, timeout: int = 30) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "nlpu-pr-demo",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def get_json(
        self, url: str, params: dict[str, Any] | None = None
    ) -> tuple[Any, dict[str, str]]:
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers=self.headers, method="GET")

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                    response_headers = dict(response.headers.items())
                    return json.loads(body), response_headers
            except HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if exc.code in TRANSIENT_HTTP_CODES and attempt < _MAX_ATTEMPTS:
                    self._backoff(attempt, f"temporary error {exc.code}")
                    continue
                raise RuntimeError(
                    f"GitHub API request failed: {exc.code} {exc.reason} | {error_body}"
                ) from exc
            except URLError as exc:
                if attempt < _MAX_ATTEMPTS:
                    self._backoff(attempt, "network error")
                    continue
                raise RuntimeError(f"Network error while calling GitHub API: {exc.reason}") from exc
            except (HTTPException, ConnectionError, TimeoutError) as exc:
                if attempt < _MAX_ATTEMPTS:
                    self._backoff(attempt, f"connection dropped ({type(exc).__name__})")
                    continue
                raise RuntimeError(f"Connection error while calling GitHub API: {exc}") from exc

        raise RuntimeError("GitHub API request failed after retries.")

    def paginate(
        self, url: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_url: str | None = url
        next_params = params
        while next_url:
            payload, response_headers = self.get_json(next_url, next_params)
            if not isinstance(payload, list):
                raise RuntimeError(
                    f"Expected list payload from {next_url}, got {type(payload).__name__}"
                )
            results.extend(payload)
            next_url = self.parse_next_link(response_headers.get("Link"))
            next_params = None
            time.sleep(0.2)
        return results

    def post_graphql(self, query: str, variables: dict[str, Any]) -> Any:
        payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        request = Request(
            f"{self.base_url}/graphql",
            data=payload,
            headers={**self.headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
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

    @staticmethod
    def _backoff(attempt: int, reason: str) -> None:
        wait = attempt * 2
        print(f"  GitHub API {reason}, retrying in {wait}s...")
        time.sleep(wait)
