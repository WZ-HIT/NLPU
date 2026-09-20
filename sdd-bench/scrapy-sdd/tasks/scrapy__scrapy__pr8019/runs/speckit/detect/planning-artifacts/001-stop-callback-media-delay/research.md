# Phase 0 Research: Stop Sleeping 100 ms Before Callbacks and Media Results

## Decision 1: Replace the fixed delay with a zero-delay double yield

- **Decision**: The internal helper becomes `_process_pending_io()` and yields twice with
  no delay (`await sleep(0)` then `await sleep(0)`).
- **Rationale**: A single yield can resume before the callbacks of the file descriptors
  that the last poll found ready; only the second yield is guaranteed to resume after
  them. Two zero-delay yields preserve the ordering guarantee of the old 100 ms sleep
  while removing its cost.
- **Alternatives considered**: (a) keep `sleep(0.1)` — rejected, that is the reported
  problem; (b) a single `sleep(0)` — rejected, does not guarantee the ordering;
  (c) `reactor.callLater(0, ...)` / `call_later(0, ...)` — rejected for the coroutine
  call sites because they already run inside coroutines and the existing `sleep()`
  helper abstracts asyncio vs. Twisted-only reactors.

## Decision 2: Rename the helper instead of keeping a misleading name

- **Decision**: Rename `_defer_sleep_async` to `_process_pending_io` and migrate all five
  call-site modules plus the test that imports it.
- **Rationale**: The function no longer sleeps for a duration; the name is private, so
  renaming is not an API break (FR-008, FR-009).
- **Alternatives considered**: keep the old name with new semantics — rejected because it
  documents a delay that no longer exists and would mislead future call sites.

## Decision 3: Media waiters are notified directly, with one yield before caching

- **Decision**: In `MediaPipeline._cache_result_and_execute_waiters()`, call
  `wad.callback(result)` / `wad.errback(result)` directly, and add a
  `await _process_pending_io()` in `_process_request()` immediately before caching the
  result and notifying waiters; cached-result and download-start paths also use the new
  helper.
- **Rationale**: The per-waiter `call_later(_DEFER_DELAY, ...)` delay is exactly the
  "100 ms before every media result" in the feature title. Moving the yield before the
  cache/notify step keeps results ordered against pending I/O while letting all waiters
  resolve in the same turn.
- **Alternatives considered**: `call_later(0, ...)` — rejected (still a reactor-level
  hop per waiter and depends on the reactor, while the pipeline already runs in a
  coroutine); keeping the per-waiter delay — rejected.

## Decision 4: Deprecated delayed helpers are out of scope

- **Decision**: `defer_fail()`, `defer_succeed()` and `defer_result()` keep
  `_DEFER_DELAY = 0.1` and their `ScrapyDeprecationWarning`s.
- **Rationale**: They are public, deprecated APIs whose documented contract is a delay;
  changing them would be a behavior change without deprecation (FR-010, FR-011).
- **Alternatives considered**: migrate them too — rejected as an unrelated breaking change.

## Decision 5: `sleep(0)` is supported on both reactor configurations

- **Decision**: Use the existing `scrapy.utils.asyncio.sleep()` for the zero yields.
- **Rationale**: Without asyncio it delegates to
  `twisted.internet.task.deferLater(reactor, seconds)`, which schedules a zero-delay call;
  with asyncio it uses `asyncio.sleep(0)`. Both are valid with `seconds == 0`, and the
  helper is already imported by `scrapy/utils/defer.py`.
- **Alternatives considered**: `asyncio.sleep(0)` directly — rejected, breaks the
  Twisted-only (`--reactor=default`) configuration.

## Open Items

None. All unknowns from the Technical Context in `plan.md` were resolved; no
`NEEDS CLARIFICATION` markers remain in the specification.
