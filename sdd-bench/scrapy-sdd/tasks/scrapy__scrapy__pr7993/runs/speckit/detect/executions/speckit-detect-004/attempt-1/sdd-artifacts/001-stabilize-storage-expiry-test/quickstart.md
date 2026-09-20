# Quickstart Validation: Stabilize Storage Expiry Test

## Purpose

Validate that the cache-storage expiration test verifies fresh and expired states deterministically without relying on runner speed.

## Prerequisites

- Use the repository's supported Python environment and test dependencies.
- This planning task must not execute tests; these steps are for the later implementation phase.

## Validation Scenario

1. Review `tests/test_downloadermiddleware_httpcache.py` and confirm the shared storage test establishes a controlled reference time before storing the response.
2. Confirm the first retrieval and response-content checks occur before the controlled time crosses the expiration threshold.
3. Confirm only the later retrieval occurs beyond the expiration threshold and expects a missing response.
4. Run the targeted expiration tests in the later implementation phase:

   ```bash
   pytest tests/test_downloadermiddleware_httpcache.py -k "test_storage"
   ```

5. Repeat the targeted run enough times to cover slow scheduling and confirm there are no false pre-expiry misses.

## Expected Outcome

- The first retrieval always returns the stored response regardless of real elapsed runner time.
- The later retrieval always reports a cache miss.
- Filesystem, gzip filesystem, DBM, and custom DBM variants retain the same shared coverage.
- No production file changes are needed.
