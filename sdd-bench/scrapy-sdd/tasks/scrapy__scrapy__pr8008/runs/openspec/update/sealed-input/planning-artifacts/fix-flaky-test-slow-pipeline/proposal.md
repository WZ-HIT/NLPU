## Why

`tests/test_spider_start.py::test_slow_pipeline` is flaky: it asserts that scraped
items arrive in submission order (A then B), but `SlowPipeline.process_item` applies
the same artificial delay to both items, so their completion order is decided by
event-loop scheduling and timer resolution rather than by submission order. The
assertion was reproduced failing on the Windows "min" CI job, where timer
resolution is coarser (scrapy/scrapy#8006).

## What Changes

- `_test_spider()` in `tests/test_spider_start.py` gains an `ordered: bool = True`
  parameter. The default keeps the existing strict item-order comparison, so every
  other test that uses the helper is unaffected.
- `test_slow_pipeline` calls `_test_spider(..., ordered=False)` so it compares the
  scraped items to the expected items without depending on completion order.
- No production code changes: `scrapy/` is untouched and no item-ordering guarantee
  of the framework is altered or removed. This is a test-only stabilization.

## Capabilities

### New Capabilities

None. This change alters no externally observable system behavior; it only removes
a scheduling-dependent assumption from an existing test, so there is no behavior to
specify. Per the OpenSpec contract that specs describe behavior, this change sets
`skip_specs: true` in `.openspec.yaml` instead of inventing a requirement.

### Modified Capabilities

None. No existing requirement under `openspec/specs/` changes, because the framework's
item pipeline behavior is unchanged; only the test's expectation is made
order-insensitive.

## Impact

- Affected code: `tests/test_spider_start.py` only (test helper `_test_spider` and the
  `test_slow_pipeline` test case). Tests that pass `expected_items` continue to get the
  strict-order assertion through the `ordered=True` default.
- Affected APIs: none. No public API, setting, dependency, or documentation change.
- Risk to users: none; this change cannot affect shipped behavior because it does not
  touch `scrapy/`.
