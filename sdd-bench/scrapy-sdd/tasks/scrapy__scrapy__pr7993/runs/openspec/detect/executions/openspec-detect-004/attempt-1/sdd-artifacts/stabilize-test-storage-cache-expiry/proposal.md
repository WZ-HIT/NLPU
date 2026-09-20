## Why

`StorageTestMixin.test_storage` configures a one-second cache expiration, stores a
response, and immediately expects that response to be retrievable. On a slow test
runner, more than one second can elapse between storing and retrieving it, causing
the entry to expire and producing a false failure.

## What Changes

- Make the `test_storage` freshness assertion deterministic by controlling the
  simulated clock around storage and retrieval instead of relying on a short
  real-time window.
- Keep the existing assertion that an entry older than
  `HTTPCACHE_EXPIRATION_SECS` is treated as a cache miss.
- Do not change production cache behavior or public APIs.

## Capabilities

### New Capabilities

None. This change only stabilizes an existing test and does not introduce or
modify externally observable behavior.

### Modified Capabilities

None.

## Impact

The affected test is
`tests/test_downloadermiddleware_httpcache.py`, primarily
`StorageTestMixin.test_storage` and the concrete storage/policy test classes that
inherit it. Production code and dependencies are unaffected.
