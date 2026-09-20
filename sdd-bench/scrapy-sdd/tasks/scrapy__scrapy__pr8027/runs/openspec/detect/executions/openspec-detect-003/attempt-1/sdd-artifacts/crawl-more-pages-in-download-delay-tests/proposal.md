## Why

The fixed and randomized download-delay tests currently compute their timing
average from a crawl that visits only a few distinct pages. Repeated links can
be skipped by request deduplication, leaving too few samples for the timing
assertion to be reliable.

## What Changes

- Increase the number of distinct pages crawled by the download-delay tests.
- Ensure the selected crawl parameters exercise more pages rather than allowing
  generated links to be skipped as duplicates.
- Keep the existing no-delay control assertion so the test parameters continue
  to prove that the measured timing difference is caused by the download delay.

## Capabilities

### New Capabilities

None. This is a test-reliability change with no product behavior change.

### Modified Capabilities

None. The change only affects how existing behavior is exercised by tests.

## Impact

Affected tests: `tests/test_crawl.py`, specifically the fixed and randomized
download-delay tests and their shared delay-test helper. No production code,
public API, dependency, or runtime behavior changes are intended.
