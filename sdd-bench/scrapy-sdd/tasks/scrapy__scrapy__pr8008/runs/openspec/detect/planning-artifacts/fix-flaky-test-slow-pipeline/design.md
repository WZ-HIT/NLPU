## Context

See `proposal.md` - Why. `tests/test_spider_start.py` drives the crawler through
`_test_spider()`, which collects `item_scraped` signals into `actual_items` and
asserts `actual_items == expected_items`. `test_slow_pipeline` scrapes two items
through a pipeline whose `process_item` awaits `scrapy.utils.asyncio.sleep(0.1)` for
every item, so both items hold the engine for the same duration and finish in
whatever order the event loop resolves their timers. The helper's strict list
comparison therefore asserts a scheduling outcome, not a framework guarantee.

Constraints: the repository is the upstream `scrapy/scrapy` tree; the change is
confined to test code, and every other caller of `_test_spider()` must keep its
current strict-order assertion.

## Goals / Non-Goals

Goals:

- Remove the speed/scheduling dependence from `test_slow_pipeline` while still
  verifying that both items are scraped and the crawl finishes cleanly.
- Keep the strict-order comparison available, and on by default, for the helper's
  other callers.

Non-Goals:

- Changing how the engine, scheduler, or item pipelines order work; the framework
  makes no ordering promise here, so no production behavior is "fixed".
- Rewriting `_test_spider()` into a richer assertion helper or changing the
  `coroutine_test` decorator usage.
- Relaxing any assertion other than the item-sequence comparison of this one test.

## Decisions

1. Add an opt-in `ordered: bool = True` keyword argument to `_test_spider()` rather
   than changing the default comparison. Rationale: the default preserves the
   existing contract for `test_start_urls`, `test_start`, `test_start_subclass`,
   `test_asyncio_delayed`, and `test_twisted_delayed`, which scrape a single item or
   genuinely depend on submission order, so the fix stays scoped to the flaky test.
   Alternative considered: sort both lists before comparing. Rejected because the
   items are plain dicts with no dedicated sort key, and sorting would silently hide
   real duplicate/omission bugs.
2. Compare as multisets (`sorted(..., key=repr)`-style or `collections.Counter`)
   instead of comparing `set(...)`. Rationale: the test should still detect a lost
   or duplicated item; only the ordering assumption is dropped. Implementation should
   use an order-insensitive comparison of the collected item dicts that keeps
   multiplicity (e.g. comparing `Counter(map(repr, actual_items))` with the same for
   `expected_items`).
3. Pass `ordered=False` only from `test_slow_pipeline`. Rationale: it is the only
   test that submits more than one item through a uniformly delayed pipeline.

## Risks / Trade-offs

- [Relaxing the assertion could hide a future ordering regression] -> The framework
  does not guarantee pipeline completion order, and the test keeps its length and
  content assertions via the multiset comparison, so a dropped or duplicated item
  still fails.
- [A helper signature change could break other callers] -> `ordered` is keyword-only
  with a default of `True`, so all existing positional calls keep their behavior;
  the existing tests for single-item spiders continue to exercise the ordered path.
- [Flakiness could persist from a different cause] -> Verification relies on repeated
  runs of the single test rather than a single pass (see `tasks.md`).

## Migration Plan

Not applicable: test-only change, no deployment, data migration, or rollback path.
The edit and its reversion are both a single test-file change.

## Open Questions

None.
