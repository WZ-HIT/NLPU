# Quickstart Validation: Fix open_in_browser ReDoS Test Flakiness and a Broken Exploit Input

This guide lists the runnable validation scenarios for the feature. It is a
run guide, not an implementation: the actual assertions live in
`tests/test_utils_response.py` and are described in
[contracts/redos-regression-contract.md](./contracts/redos-regression-contract.md)
and [data-model.md](./data-model.md).

## Prerequisites

- A checkout at the feature branch with Scrapy's test dependencies installed.
- No network access and no real browser are required.

## Scenario 1 — ReDoS regression tests are deterministic

```bash
pytest tests/test_utils_response.py -k "redos" -q
```

Expected: both ReDoS tests pass; repeating the command (including while the
worker is under CPU load) keeps passing, because the decision no longer depends
on absolute machine speed.

## Scenario 2 — Exploit bodies actually attack the removed patterns

```bash
pytest tests/test_utils_response.py -k "redos" -q
```

Expected: each ReDoS test first asserts that its body leaves the target removed
pattern without an early match, so a body that provides the closing delimiter
fails the test instead of silently passing it.

## Scenario 3 — Viewer behaviour is unchanged

```bash
pytest tests/test_utils_response.py -q
pytest tests/test_commands.py -k "ViewCommand" -q
```

Expected: comment preservation, single-base-tag injection, doctype placement,
`.txt` handling for text responses, `TypeError` for unsupported responses, and
the `scrapy view` end-to-end path all behave exactly as before.

## Scenario 4 — The regression tests fail against a vulnerable implementation

In a scratch copy only, reinstate a removed pattern (for example comment
stripping with `<!--.*?-->`) and rerun Scenario 1.

Expected: the corresponding ReDoS test fails, proving the suite still detects
catastrophic backtracking. Do not commit the reinstated pattern.

## Success indicators

- 100% pass rate over repeated runs of Scenario 1, including under CPU
  contention (SC-001).
- Exploit bodies exceed the cost budget under the removed patterns by at least
  two orders of magnitude and stay below 10% of it under the shipped
  implementation (SC-002).
- Both reinstatement checks fail as expected (SC-003).
- No pre-existing assertion removed or relaxed (SC-004).
