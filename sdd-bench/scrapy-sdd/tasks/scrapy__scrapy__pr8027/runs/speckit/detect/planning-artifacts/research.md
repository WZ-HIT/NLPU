# Research: Download Delay Crawl Coverage

## Decision: Reuse the crawl-level delay tests

**Rationale**: `tests/test_crawl.py` contains the fixed-delay and randomized-delay scenarios, and `FollowAllSpider` already records per-response timestamps. Increasing the page count directly addresses the PR without changing production code.

**Alternatives considered**:

- Adding a new timing fixture: rejected because the timing helper already covers the contract.
- Skipping timing-sensitive cases: rejected by the task title and because it reduces coverage.
- Using the downloader-slot delay test: rejected because it verifies per-slot configuration, not a multi-page crawl.

## Decision: Preserve the no-delay control crawl

**Rationale**: The control demonstrates that the selected page count and delay are large enough for the delayed assertion to be meaningful.

**Alternatives considered**:

- Removing the control: rejected because it would make the timing assertion vulnerable to meaningless parameters.
- Hard-coding expected wall time: rejected because it is platform- and load-sensitive.

## Detected candidates

- `tests/test_crawl.py`: `TestCrawl.test_fixed_delay`, `TestCrawl.test_randomized_delay`, supported by `TestCrawl._test_delay`.
