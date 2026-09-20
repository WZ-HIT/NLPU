## Why

Three tests are still skipped on Windows with the asyncio reactor solely because they previously produced `DirtyReactorAggregateError`. The pull request re-checks whether those guards remain necessary so the tests can provide coverage again.

## What Changes

- Remove the Windows/asyncio skip guards from the affected download-handler tests if the historical reactor failure no longer occurs.
- Remove now-unused `reactor_pytest` parameters from the re-enabled tests.
- Preserve all existing assertions and test behavior.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is test-maintenance work and does not change documented Scrapy behavior.

## Impact

Affected tests cover Twisted FTP download-handler authentication and HTTP download-handler timeout behavior. The candidate implementations are exercised through the Twisted HTTP/1.1, HTTP/2, Httpx, and FTP test modules.
