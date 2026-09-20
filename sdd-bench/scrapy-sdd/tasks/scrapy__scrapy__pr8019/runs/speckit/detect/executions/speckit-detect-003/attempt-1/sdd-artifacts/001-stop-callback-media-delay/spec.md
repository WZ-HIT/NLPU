# Feature Specification: Stop Sleeping 100 ms Before Callbacks and Media Results

**Feature Branch**: `001-stop-callback-media-delay`

**Created**: 2026-09-19

**Status**: Draft

**Input**: Pull request `scrapy/scrapy#8019` — "Stop sleeping 100 ms before every callback and media result" (base commit `916039ca4ca79ea4ed38e74d71e25c2584c1925e`)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Callbacks Run Without an Artificial Delay (Priority: P1)

A spider author runs a crawl whose pages produce many small responses. Every response
is handled by a callback (or errback). The engine waits roughly 100 ms before handing
control to that callback, even though nothing is pending that needs the wait. The user
wants each response to reach its callback as soon as the transport work for it is done,
so a crawl that should take seconds does not accumulate an extra tenth of a second per
handled response.

**Why this priority**: This is the dominant user-visible effect of the change and the
main throughput/latency win. It is also the highest-traffic code path: every single
response goes through it.

**Independent Test**: Crawl a mock site that serves several pages to a spider whose
callback records when it was invoked. The crawl completes and every response is
delivered to its callback, with no fixed per-response delay observable between the
response becoming available and the callback being invoked.

**Acceptance Scenarios**:

1. **Given** a spider with an asynchronous callback, **When** a response is downloaded and no pending reader/writer work remains, **Then** the callback starts without the engine waiting a fixed ~100 ms first.
2. **Given** a spider whose callback raises, **When** the error is handled by the engine, **Then** pending transport callbacks are still given a chance to run before the failure is processed, but no fixed ~100 ms wait is inserted.
3. **Given** a run of many sequential requests, **When** each response is processed, **Then** total crawl time does not grow by a fixed ~100 ms per response.

---

### User Story 2 - Media Results Are Delivered Without an Artificial Delay (Priority: P2)

A spider author uses the file/image pipelines (or a custom media pipeline) and writes
items that reference the same media URL more than once, including across items. The
pipeline de-duplicates downloads by fingerprint: the first request downloads, later
requests either reuse the cached result or wait for the in-flight download. Each cached
result and each waiter notification currently pays a ~100 ms delay before the result
becomes available.

**Why this priority**: Media-heavy crawls issue the same URL repeatedly (thumbnails,
shared assets), so the delay multiplies. The behavior must change without losing the
de-duplication and result-caching guarantees.

**Independent Test**: Process items that request the same media URL twice in one item
and again in a later item. Exactly one download happens; both waiting requests and the
cached request receive the same result; no fixed ~100 ms delay is inserted on the
cached path, the download start path, or the waiter notification path.

**Acceptance Scenarios**:

1. **Given** a media request whose fingerprint is already cached, **When** a new request for that fingerprint is processed, **Then** the cached result is returned promptly (no fixed ~100 ms delay) and any request errback is still honored.
2. **Given** two concurrent media requests with the same fingerprint, **When** the first finishes, **Then** all waiters are notified with the same result and the second request is not downloaded again.
3. **Given** a cached media failure, **When** it is replayed, **Then** the failure is still raised/logged exactly as before and the request errback still runs.

---

### User Story 3 - Internal Yielding Still Protects Pending I/O (Priority: P3)

Scrapy developers rely on the engine giving the event loop a chance to complete
pending reader/writer callbacks before a callback result or media result is delivered.
This ordering exists for correctness (for example, releasing download slots and
signalling that a request left the downloader). The delay must be removed without
removing that guarantee.

**Why this priority**: This is the safety property that makes the optimizations in
User Stories 1 and 2 acceptable; it is lower priority only because it has no new
user-visible behavior of its own.

**Independent Test**: Exercise the downloader, downloader middleware, spider
middleware and scraper error paths together with the media pipeline and confirm that
results/callbacks are still delivered only after pending transport callbacks have been
processed, and that the helper performing this yield is no longer described or
implemented as a fixed sleep.

**Acceptance Scenarios**:

1. **Given** a component that must yield to pending transport callbacks, **When** it resumes, **Then** the previously pending reader/writer callbacks have been given the opportunity to run.
2. **Given** the deprecated deferred helpers (`defer_fail`, `defer_succeed`, `defer_result`), **When** they are used, **Then** they keep their existing delayed behavior and deprecation warnings.

---

### Edge Cases

- A media result is produced while other waiters for the same fingerprint are still being appended: every waiter present in the waiting list at completion time must be notified exactly once.
- A cached media *failure* is replayed for a request that has an errback: the errback must still run and the pipeline must not raise a duplicate unhandled exception.
- The same fingerprint downloads concurrently in both asyncio and Twisted-only modes: waiters must be resolved in both.
- A spider callback returns a generator / async generator / awaitable: yielding behavior must be unchanged with respect to output processing.
- A crawl where nothing else wakes the engine: removing the fixed delay must not cause the engine to stall or miss work.
- Deprecated helper `scrapy.utils.defer.defer_result()` / `defer_succeed()` / `defer_fail()` must be unaffected by the rename.
- Tests that currently import the internal helper by name must keep working after the rename (internal name change must be applied consistently).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The engine MUST invoke a spider callback/errback for a downloaded response without inserting a fixed ~100 ms delay beforehand.
- **FR-002**: Before a callback/errback is invoked (or a failure is processed), the engine MUST still yield control so that pending transport reader/writer callbacks get a chance to run.
- **FR-003**: The media pipeline MUST return an already-cached media result without inserting a fixed ~100 ms delay.
- **FR-004**: The media pipeline MUST begin the work of a not-yet-cached media request without inserting a fixed ~100 ms delay.
- **FR-005**: When a media result becomes available, the pipeline MUST notify every waiting deferred for that fingerprint without inserting a fixed ~100 ms delay, while still yielding to the event loop before the result is cached and waiters are notified.
- **FR-006**: Downloader slot handling MUST still release the request from the transferring set and emit the "request left downloader" signal when a download fails, without inserting a fixed ~100 ms delay before the failure is re-raised.
- **FR-007**: Downloader middleware and spider middleware exception paths MUST still yield to the event loop before handling a raised exception, without inserting a fixed ~100 ms delay.
- **FR-008**: The internal yielding helper MUST be named and documented in terms of processing pending I/O rather than sleeping for a fixed duration.
- **FR-009**: All call sites of the former fixed-delay helper MUST be migrated to the new helper; no call site may keep the fixed delay.
- **FR-010**: Deprecated public helpers that intentionally delay (`scrapy.utils.defer.defer_fail`, `defer_succeed`, `defer_result`) MUST retain their current fixed delay and deprecation warnings.
- **FR-011**: The change MUST NOT alter any public API, configuration setting, signal name, or documented behavior other than the removed delay.
- **FR-012**: Media de-duplication semantics MUST be preserved: one download per fingerprint per spider, shared results for waiters, cached successes and cached failures replayed identically.

### Key Entities

- **Pending I/O yield**: the operation that hands control back to the event loop long enough for already-ready reader/writer callbacks to run, then resumes; characterized by "how many yields" are needed to make the guarantee.
- **Callback invocation**: the step that turns a downloaded response (or failure) into spider callback output.
- **Media request fingerprint**: identity of a media request used for de-duplication; each fingerprint has a lifecycle with `downloading`, `waiting`, and `downloaded` state.
- **Media waiter**: a deferred handed out to a duplicate request that resolves with the shared result/failure once the owning download completes.
- **Deprecated delayed helpers**: `defer_fail`, `defer_succeed`, `defer_result` (unchanged behavior, still delay).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Processing a response whose callback does no work no longer consumes a fixed ~100 ms before the callback runs; the added engine-side delay per callback is below 1 ms on a normal machine.
- **SC-002**: A crawl of 100 sequential mock pages that previously spent ~10 s waiting in per-callback delays completes in a small fraction of that time, with no page lost.
- **SC-003**: Serving the same media URL 10 times within one crawl still performs exactly 1 download, and every reference receives the identical result value (success or failure).
- **SC-004**: Zero regressions in the existing test suite: all currently passing tests in the affected areas still pass, and the tests that reference the renamed internal helper are updated.
- **SC-005**: No public interface changes are detected by the project's existing deprecation/interface tests.

## Assumptions

- The 100 ms delay is a deliberate historical safeguard ("give the reactor a chance to go through readers and writers"); the feature keeps the safeguard but removes the fixed cost.
- Yielding to the event loop twice with a zero delay is sufficient to make the ordering guarantee; a single yield is not, because the first resume can happen before the callbacks of ready file descriptors run.
- The deprecated helpers `defer_fail`, `defer_succeed`, `defer_result` stay on the old fixed-delay behavior; only internal call sites are migrated.
- `scrapy.utils.asyncio.sleep()` accepts `0` in both the asyncio and Twisted-only code paths.
- Test selection for this feature uses the existing pytest suite; no new test framework or configuration is introduced.
