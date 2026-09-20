# Quickstart Validation: Stop Sleeping 100 ms Before Callbacks and Media Results

This guide lists the runnable scenarios that prove the feature works end to end. It is
a validation/run guide only; implementation detail lives in `tasks.md`.

## Prerequisites

- Repository checkout at the feature branch with the source changes applied.
- Development environment capable of running the project test suite (pytest plus
  `pytest-twisted`/`pytest-asyncio`, and the `--reactor` option).
- No network access required: the suite uses `tests/mockserver` and local fixtures.

## Scenario 1 - Renamed helper is consistent (FR-008, FR-009)

1. Confirm `scrapy/utils/defer.py` defines `_process_pending_io` and no longer defines
   `_defer_sleep_async`.
2. Confirm `tests/test_pipeline_media.py` imports the new name.
3. Run: `pytest tests/test_utils_defer.py` and `pytest tests/test_pipeline_media.py`.

**Expected**: both modules import cleanly and pass; no fixed 100 ms delay remains on
the migrated paths.

## Scenario 2 - Callbacks are not delayed (FR-001, FR-002, SC-001, SC-002)

1. Run: `pytest tests/test_crawl.py tests/test_core_scraper.py`.
2. Compare wall-clock time of a many-page mock crawl before/after the change.

**Expected**: all responses reach their callbacks/errbacks; the per-response fixed
delay is gone; crawl duration drops by roughly 100 ms per handled response.

## Scenario 3 - Media results are not delayed and stay de-duplicated (FR-003, FR-004, FR-005, FR-012, SC-003)

1. Run: `pytest tests/test_pipeline_media.py tests/test_pipeline_crawl.py`.
2. Run: `pytest tests/test_pipeline_files.py tests/test_pipeline_images.py`.

**Expected**: one download per fingerprint; waiters and cached requests receive the
same result; cached failures still invoke request errbacks; no fixed delay on any of
the cached, download-start or waiter-notification paths.

## Scenario 4 - Error paths still yield to pending I/O (FR-006, FR-007)

1. Run: `pytest tests/test_downloadermiddleware.py tests/test_spidermiddleware.py tests/test_request_left.py`.
2. Run the same selection with the Twisted-only reactor (`--reactor=default`) and with
   asyncio (`--reactor=asyncio`).

**Expected**: exceptions surface as before, `request_left_downloader` is still emitted
once per request, and the transferring set is still cleaned up.

## Scenario 5 - Deprecated helpers unchanged (FR-010)

1. Run the deprecation-focused tests in `tests/test_utils_defer.py`.

**Expected**: `defer_fail()`, `defer_succeed()` and `defer_result()` still warn and
still delay by the historical amount.

## Scenario 6 - No public surface changed (FR-011, SC-005)

1. Run the suite's interface/deprecation tests plus a full `pytest` run.

**Expected**: no new failures relative to the base commit.
