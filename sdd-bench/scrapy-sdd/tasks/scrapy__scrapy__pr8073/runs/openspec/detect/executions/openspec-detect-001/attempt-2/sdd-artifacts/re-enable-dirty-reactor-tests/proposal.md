## Why

Three tests are still skipped on Windows when the asyncio reactor is used because they previously produced `DirtyReactorAggregateError`. The skips may be obsolete, but they hide real coverage on that supported test configuration.

## What Changes

- Remove the Windows-asyncio skip from `TestFTP::test_invalid_credentials` and remove its now-unused `reactor_pytest` argument.
- Remove the Windows-asyncio skips from `TestHttpBase::test_timeout_download_from_spider_nodata_rcvd` and `TestHttpBase::test_timeout_download_from_spider_server_hangs`, including their now-unused `reactor_pytest` arguments.
- Keep all test assertions and production behavior unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This change only re-enables existing test coverage and does not change externally observable system behavior, so no spec deltas are required (`skip_specs: true`).

## Impact

- `tests/test_downloader_handler_twisted_ftp.py`
- `tests/utils/bases/download_handlers_http.py`
