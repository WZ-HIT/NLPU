## Context

The project defines a `requires_internet` pytest marker in `pyproject.toml`.
Three handler test modules mark their `TestRealWebsite` classes with it. These
tests exercise public endpoints and are inherently sensitive to transient
network failures.

## Goals / Non-Goals

**Goals:**

- Retry failures only for tests marked `requires_internet`.
- Bound the number of attempts so persistent failures still fail CI.
- Leave the tests' assertions and all other markers unchanged.

**Non-Goals:**

- Retrying unrelated flaky tests.
- Replacing real-network tests with mocks.
- Changing Scrapy download-handler behavior.

## Decisions

- Implement retries at the pytest/test-infrastructure layer by making the
  `requires_internet` marker imply a small bounded rerun count. This keeps the
  policy centralized and avoids duplicating decorators across test classes.
- Keep the retry count small and expose it through test configuration if the
  chosen pytest plugin supports doing so. A successful rerun means CI continues;
  an exhausted retry budget still produces a failure and preserves the final
  traceback.

## Risks / Trade-offs

[Transient failures may still exhaust the retry budget] -> Log each attempt and
retain the final failure so the cause remains diagnosable.

[Retries increase CI time when the network is unavailable] -> Use a small,
bounded retry count and apply it only to the `requires_internet` marker.

## Migration Plan

Deploy with the normal CI configuration change. Revert the retry configuration
if it masks reproducible failures or materially increases test duration.
