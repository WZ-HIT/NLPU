# Tasks: Safe Shutdown Signal Logging

**Input**: Design documents from `/workspace/specs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md

## Phase 1: Setup

- [ ] T001 Review the two shutdown implementations in `scrapy/crawler.py` and confirm the current synchronous logging call sites.

## Phase 2: Foundational

- [ ] T002 Confirm `_log_shutdown()` and `_log_kill()` remain the single implementations of the graceful and forced messages in `scrapy/crawler.py`.
- [ ] T003 Confirm the reactor and event-loop dispatch APIs available in `scrapy/crawler.py`.

## Phase 3: User Story 1 - Defer Twisted shutdown logging (Priority: P1)

**Goal**: Remove synchronous logging from Twisted signal-handler bodies.

**Independent Test**: Invoke the Twisted handlers with a fake reactor and assert
logging is queued via `callFromThread`.

- [ ] T004 [US1] Update `CrawlerProcessBase._signal_shutdown()` in `scrapy/crawler.py` to queue `_log_shutdown()` with `reactor.callFromThread()`.
- [ ] T005 [US1] Update `CrawlerProcessBase._signal_kill()` in `scrapy/crawler.py` to queue `_log_kill()` with `reactor.callFromThread()`.
- [ ] T006 [US1] Preserve handler escalation and reactor stop calls in `scrapy/crawler.py`.

## Phase 4: User Story 2 - Defer reactorless shutdown logging (Priority: P2)

**Goal**: Remove synchronous logging from reactorless signal-handler bodies.

**Independent Test**: Invoke the reactorless handlers with a controlled loop and
assert logging plus task control are scheduled with `call_soon_threadsafe`.

- [ ] T007 [US2] Update `AsyncCrawlerProcess._signal_shutdown_reactorless()` in `scrapy/crawler.py` to queue `_log_shutdown()` on the active loop.
- [ ] T008 [US2] Update `AsyncCrawlerProcess._signal_kill_reactorless()` in `scrapy/crawler.py` to queue `_log_kill()` before main-task cancellation.
- [ ] T009 [US2] Preserve no-loop and no-main-task behavior in `scrapy/crawler.py`.

## Phase 5: Detection and Validation

- [ ] T010 Inspect `tests/test_crawler.py` for direct assertions on the affected reactorless helpers.
- [ ] T011 Inspect `tests/test_crawler_subprocess.py` for graceful and forced shutdown message assertions.
- [ ] T012 Record the candidate test files and affected symbols in `specs/detection-draft.json` without modifying tests.

## Dependencies

- T004-T005 depend on T001-T003.
- T007-T008 depend on T001-T003.
- T010-T012 are independent inspection tasks.

## Implementation Strategy

Deliver User Story 1 first, then apply the equivalent queueing pattern to User
Story 2. Do not run tests or modify code/tests during the detect phase.
