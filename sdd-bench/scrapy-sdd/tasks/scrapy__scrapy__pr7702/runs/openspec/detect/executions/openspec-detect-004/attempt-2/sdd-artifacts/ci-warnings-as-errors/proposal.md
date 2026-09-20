## Why

Scrapy's CI currently permits Python warnings to pass silently, so warnings introduced by Scrapy or its dependencies can accumulate until they become failures in a later environment. Treating warnings as errors gives contributors immediate feedback and prevents new warning regressions.

## What Changes

- Configure the test suite to treat warnings as errors across CI environments.
- Add narrowly scoped filters only where a warning is expected, third-party, or otherwise outside Scrapy's immediate control.
- Update affected tests and warning-producing code paths so the suite remains green under the stricter policy.
- Keep the policy consistent across supported Python and dependency environments instead of enabling it only for "latest" jobs.

## Capabilities

This is a test/CI quality-assurance change. It does not change Scrapy's public runtime behavior, APIs, or configuration semantics, so no capability spec is added.

### New Capabilities

None.

### Modified Capabilities

None.

## Impact

- `pyproject.toml` and/or tox/CI environment configuration.
- Tests that currently emit unhandled warnings or rely on broad warning suppression.
- Any production code paths whose warnings need to be made explicit or corrected.
- Contributors and maintainers gain earlier warning feedback; runtime compatibility remains unchanged.
