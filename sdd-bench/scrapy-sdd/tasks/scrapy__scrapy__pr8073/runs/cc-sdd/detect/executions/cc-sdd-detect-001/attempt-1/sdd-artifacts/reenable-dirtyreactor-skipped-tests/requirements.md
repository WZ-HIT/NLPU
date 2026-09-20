# Requirements Document

## Introduction

The scrapy test suite skips three tests on Windows when the Twisted asyncio reactor (`--reactor asyncio`) is selected, because those tests emit `DirtyReactorAggregateError` and fail the run. The repository snapshot at base commit `11079cb1c85b9e75a39a7269943c69d1a975d485` contains exactly three such sites, each annotated with the skip reason `"This test produces DirtyReactorAggregateError on Windows with asyncio"`:

1. `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd` in `tests/utils/bases/download_handlers_http.py` (guard at lines 365-369).
2. `TestHttpBase.test_timeout_download_from_spider_server_hangs` in `tests/utils/bases/download_handlers_http.py` (guard at lines 383-387), both carrying the Twisted ticket 10279 reference comment.
3. `TestFTP.test_invalid_credentials` in `tests/test_downloader_handler_twisted_ftp.py` (guard at lines 176-180).

Pull request `scrapy/scrapy#8073` ("Re-enable tests with DirtyReactorAggregateError comments.") checks whether those skips are still required and, if they are not, restores the coverage that the comments removed. The requirements below describe the re-enabled behavior in user-observable, test-observable terms; they do not prescribe the editing procedure.

## Boundary Context (Optional)

- **In scope**: the three test functions listed above, the inline skip guards attached to them, and the imports that only exist to serve those guards.
- **Out of scope**: production code under `scrapy/`, reactor installation and event-loop policy in `conftest.py`, and any other Windows/asyncio skip that is not annotated with a `DirtyReactorAggregateError` comment.
- **Adjacent expectations**: the concrete download-handler test modules (`tests/test_downloader_handler_httpx.py`, `tests/test_downloader_handler_twisted_http11.py`, `tests/test_downloader_handler_twisted_http2.py`) inherit the two base-class tests and therefore continue to be the execution entry points for them; they are expected to run those tests unchanged.

## Requirements

### Requirement 1: Re-enabled HTTP download-handler timeout coverage

**Objective:** As a scrapy maintainer running the test suite with `--reactor asyncio` on Windows, I want the HTTP download-handler timeout tests to execute instead of being skipped, so that timeout regressions are detected on that configuration.

#### Acceptance Criteria

1. When the test suite is collected with `--reactor asyncio`, the `TestHttpBase` timeout tests defined in `tests/utils/bases/download_handlers_http.py` shall be collected and reported as executed (`passed`, `failed`, `error`) rather than as skipped.
2. The system shall not skip `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd` or `TestHttpBase.test_timeout_download_from_spider_server_hangs` on the basis of the `DirtyReactorAggregateError` reason.
3. The system shall keep the assertion behavior of both timeout tests unchanged: `test_timeout_download_from_spider_nodata_rcvd` shall raise `DownloadTimeoutError` for a client that connects but receives no data, and `test_timeout_download_from_spider_server_hangs` shall raise `DownloadTimeoutError` for a server that sends headers and hangs.

### Requirement 2: Re-enabled FTP download-handler coverage

**Objective:** As a scrapy maintainer running the test suite with `--reactor asyncio` on Windows, I want the FTP invalid-credentials test to execute instead of being skipped, so that FTP authentication error handling is validated on that configuration.

#### Acceptance Criteria

1. When the test suite is collected with `--reactor asyncio`, `TestFTP.test_invalid_credentials` in `tests/test_downloader_handler_twisted_ftp.py` shall be collected and reported as executed rather than as skipped.
2. The system shall not skip `TestFTP.test_invalid_credentials` on the basis of the `DirtyReactorAggregateError` reason.
3. The system shall keep the assertion behavior of the test unchanged: an invalid FTP password shall cause `dh.download_request(request)` to raise `twisted.protocols.ftp.ConnectionLost`.

### Requirement 3: No skip for unrelated platforms or non-reactor configurations

**Objective:** As a scrapy maintainer, I want the re-enabled tests to keep running normally on every other supported configuration, so that re-enabling them cannot silently disable coverage elsewhere.

#### Acceptance Criteria

1. While the test suite runs without an explicit asyncio reactor selection (default reactor), the system shall execute the three tests as before.
2. Where the test suite runs on platforms other than Windows, the system shall not introduce any new skip, xfail, or `requires_internet`-style marker for the three tests.
3. If a future regression makes one of the three tests fail on Windows with asyncio again, then the failure shall surface as a test failure or error, not as a silent skip.

### Requirement 4: Test module hygiene after the guards are removed

**Objective:** As a scrapy contributor, I want the touched test modules to stay lint-clean, so that the change does not leave dead imports behind.

#### Acceptance Criteria

1. When the `DirtyReactorAggregateError` guard is removed from `tests/test_downloader_handler_twisted_ftp.py`, the system shall not retain a module-level import that is used only by that guard.
2. The system shall not change module-level imports in `tests/utils/bases/download_handlers_http.py` that remain in use by other tests (for example the `sys` uses for the Windows version guard and the macOS-only markers).
3. The system shall preserve existing module docstrings, `pytestmark` declarations, and test ordering in both files.
