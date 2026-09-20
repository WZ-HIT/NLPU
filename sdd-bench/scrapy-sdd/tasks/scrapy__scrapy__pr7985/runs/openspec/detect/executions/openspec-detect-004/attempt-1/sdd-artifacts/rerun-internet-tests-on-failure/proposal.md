## Why

Tests that require real Internet access can fail because of transient DNS, TLS,
proxy, or remote-server problems unrelated to the pull request under test. Those
failures make CI noisy and can obscure real regressions.

## What Changes

- Add automatic retries for tests marked `requires_internet`.
- Keep retries bounded and report the final failure when all attempts fail.
- Preserve the existing behavior of local and mock-server tests.

## Capabilities

### New Capabilities

None. This is CI and test-infrastructure tooling; it does not change Scrapy's
observable product behavior.

### Modified Capabilities

None.

## Impact

Affected areas are the pytest configuration and test infrastructure that
interpret the `requires_internet` marker. The three test modules that currently
use that marker are the intended validation targets.
