## Why

The two `open_in_browser` ReDoS regression tests enforce a 0.02-second CPU-time
budget. On supported slower interpreters such as PyPy, the current linear
implementation can exceed that budget, producing false failures instead of
detecting a reintroduced regular-expression denial-of-service vulnerability.

## What Changes

- Make the CPU-time guard in `test_open_in_browser_redos_comment` and
  `test_open_in_browser_redos_head` tolerant of slower interpreters.
- Keep the exploit payloads and the production `open_in_browser` implementation
  unchanged so the tests still exercise the original ReDoS regression cases.
- Add no public API, runtime behavior, or dependency changes.

## Capabilities

### New Capabilities

None. This is a test-reliability change with no new externally observable
capability.

### Modified Capabilities

None. The behavior of `open_in_browser` does not change.

## Impact

Only `tests/test_utils_response.py` is affected. Production code, public APIs,
dependencies, and documentation are unchanged.
