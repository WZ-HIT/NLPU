## Context

`tests/test_utils_response.py` contains two regression tests that feed
pathological HTML into `open_in_browser` and require completion within a fixed
0.02-second CPU-time budget. Scrapy's CI includes PyPy environments, where the
same safe implementation can take longer than CPython. See `proposal.md` for
the motivation.

## Goals / Non-Goals

**Goals:**

- Preserve coverage for the comment-removal and `<head>`-lookup ReDoS patterns.
- Allow the tests to pass on supported interpreters with different constant
  factors.
- Keep failures useful when exponential regex behavior is reintroduced.

**Non-Goals:**

- Changing `open_in_browser` or its regular expressions.
- Removing the regression tests or skipping them on PyPy.
- Adding a general-purpose performance benchmark.

## Decisions

- Replace the shared fixed 0.02-second assertion budget with a deliberately
  generous ceiling that is still far below the cost of the old exponential
  patterns on the existing payloads. This preserves the regression signal
  while avoiding dependence on interpreter-specific constant factors.
- Keep both existing exploit payloads and call the real `open_in_browser`
  implementation. Comparing against a synthetic regex or a mocked function
  would stop testing the production path.

## Risks / Trade-offs

- [A ceiling that is too high could miss a partially regressed implementation]
  → Keep the payloads unchanged and use a bound that remains orders of
  magnitude below the observed pathological behavior.
- [CPU-time measurements can still vary across CI hosts] → Use a generous
  interpreter-independent threshold and retain `process_time()` rather than
  wall-clock time so scheduler delays do not affect the assertion.

## Migration Plan

This changes test-only code with no deployment or migration requirements.
Rollback is the inverse test edit if the new threshold proves ineffective.
