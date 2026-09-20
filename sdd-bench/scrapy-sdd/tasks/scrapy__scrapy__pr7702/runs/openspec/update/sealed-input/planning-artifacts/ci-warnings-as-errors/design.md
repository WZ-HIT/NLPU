## Context

The test suite currently allows most warnings to be reported without failing the job. Warning behavior varies by Python version, dependency version, reactor choice, and optional extras, so enabling errors only in one matrix entry leaves gaps and makes the policy difficult to reason about.

## Goals / Non-Goals

- Goal: make unexpected warnings fail consistently across the CI test matrix.
- Goal: keep intentional warning tests explicit and auditable.
- Non-goal: remove deprecated public APIs or change runtime warning behavior.
- Non-goal: suppress warnings globally without identifying their source.

## Decisions

1. Enable warnings as errors at the shared pytest configuration level. This covers all environments with one policy and avoids duplicating configuration per CI job.
2. Keep exceptions narrow. Each remaining filter should identify a specific message, category, and/or module, with a comment explaining why it is safe.
3. Prefer converting expected-warning tests to `pytest.warns()` or a tightly scoped `warnings.catch_warnings()` block. Broad ignores should be replaced by assertions or scoped filters.
4. If a warning comes from Scrapy behavior that should remain, make its emission intentional in the test and assert it. If it is accidental or obsolete, fix the code path rather than hiding it.

## Risks / Trade-offs

- Third-party or interpreter warnings may differ across the matrix; these require narrow filters rather than policy-wide exceptions.
- Tests that intentionally exercise deprecated behavior may need explicit expectations to distinguish them from regressions.
- The stricter policy can expose latent warning leaks in code shared by many tests, making root-cause grouping more useful than isolated per-test suppression.

## Migration Plan

1. Turn on warning errors in shared test configuration.
2. Run the test matrix and group failures by warning source.
3. Fix Scrapy-owned warnings, make expected warnings explicit in tests, and add documented narrow filters for external noise.
4. Re-run all environments and keep the policy enabled once clean.

## Open Questions

None requiring a product decision; any remaining filter is an implementation detail to validate against the full matrix.
