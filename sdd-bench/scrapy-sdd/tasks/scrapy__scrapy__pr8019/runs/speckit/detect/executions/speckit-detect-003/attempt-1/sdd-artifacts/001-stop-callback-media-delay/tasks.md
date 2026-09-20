---

description: "Task list for stopping the 100 ms delay before callbacks and media results"
---

# Tasks: Stop Sleeping 100 ms Before Callbacks and Media Results

**Input**: Design documents from `specs/001-stop-callback-media-delay/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Test tasks are included because the rename of a private helper used by the
test suite must be applied, and the feature's success criteria are measured by the
existing pytest suite. No new test framework is added.

**Organization**: Tasks are grouped by user story. Paths are repository-relative.

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Confirm the current fixed-delay helper and all of its call sites with `grep -rn "_defer_sleep_async\\|_DEFER_DELAY" scrapy/ tests/`
- [ ] T002 Confirm `scrapy/utils/asyncio.py::sleep()` supports `seconds == 0` on both the asyncio and Twisted-only reactor paths (recorded in research.md Decision 5)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: every call-site migration depends on this phase

- [ ] T003 Rename `_defer_sleep_async()` to `_process_pending_io()` and change its body to `await sleep(0)` twice in scrapy/utils/defer.py, updating its docstring to describe processing pending I/O
- [ ] T004 [P] Keep `_DEFER_DELAY`, `defer_fail()`, `defer_succeed()` and `defer_result()` untouched (delay + `ScrapyDeprecationWarning`) in scrapy/utils/defer.py
- [ ] T005 Update the test import and usage of the renamed helper in tests/test_pipeline_media.py

**Checkpoint**: `scrapy.utils.defer._process_pending_io` exists; no module references the old name.

---

## Phase 3: User Story 1 - Callbacks Run Without an Artificial Delay (Priority: P1) 🎯 MVP

**Goal**: responses reach spider callbacks/errbacks with no fixed 100 ms wait, while still yielding to pending I/O.

**Independent Test**: crawl a mock site with a spider whose callback records invocations; every response reaches its callback and the fixed per-response delay is gone.

### Implementation for User Story 1

- [ ] T006 [US1] Import `_process_pending_io` and replace `await _defer_sleep_async()` with `await _process_pending_io()` in scrapy/core/scraper.py (`Scraper.call_spider_async`)
- [ ] T007 [P] [US1] Replace the same call in scrapy/core/spidermw.py (`SpiderMiddlewareManager.scrape_response_async` exception path)
- [ ] T008 [P] [US1] Replace the same call in scrapy/core/downloader/middleware.py (`DownloaderMiddlewareManager.download_async` exception path)
- [ ] T009 [P] [US1] Replace the same call in scrapy/core/downloader/__init__.py (`Downloader._download` failure path), leaving slot cleanup and the `request_left_downloader` signal unchanged

**Checkpoint**: no call site of the old helper remains outside `scrapy/pipelines/media.py`.

---

## Phase 4: User Story 2 - Media Results Are Delivered Without an Artificial Delay (Priority: P2)

**Goal**: cached media results, download starts and waiter notifications no longer pay 100 ms, with de-duplication preserved.

**Independent Test**: process items requesting the same media URL repeatedly; exactly one download occurs, all waiters and cached requests get the same result, no fixed delay is inserted.

### Implementation for User Story 2

- [ ] T010 [US2] In scrapy/pipelines/media.py replace the `_defer_sleep_async()` call on the cached-result path and before starting a download with `await _process_pending_io()`
- [ ] T011 [US2] In scrapy/pipelines/media.py add `await _process_pending_io()` after the result is obtained and before `_cache_result_and_execute_waiters()` is called
- [ ] T012 [US2] In `MediaPipeline._cache_result_and_execute_waiters()` call `wad.errback(result)` / `wad.callback(result)` directly instead of `call_later(_DEFER_DELAY, ...)`
- [ ] T013 [US2] Remove the now-unused `_DEFER_DELAY` and `call_later` imports from scrapy/pipelines/media.py

---

## Phase 5: User Story 3 - Internal Yielding Still Protects Pending I/O (Priority: P3)

**Goal**: the ordering guarantee survives the removal of the fixed delay on every migrated path.

**Independent Test**: run the error-path and slot-release tests on both reactor configurations and confirm ordering, cleanup and signal behavior are unchanged.

### Tests for User Story 3

- [ ] T014 [P] [US3] Verify downloader/downloader-middleware/spider-middleware exception ordering with `pytest tests/test_downloadermiddleware.py tests/test_spidermiddleware.py`
- [ ] T015 [P] [US3] Verify downloader slot release and the `request_left_downloader` signal with `pytest tests/test_request_left.py`

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T016 [P] Run the media-focused modules: `pytest tests/test_pipeline_media.py tests/test_pipeline_crawl.py tests/test_pipeline_files.py tests/test_pipeline_images.py`
- [ ] T017 [P] Run the callback-focused modules: `pytest tests/test_crawl.py tests/test_core_scraper.py tests/test_utils_defer.py`
- [ ] T018 [P] Re-run the affected selection with `--reactor=default` and `--reactor=asyncio`
- [ ] T019 Add a short release-notes entry for the removed fixed delay in docs/news.rst
- [ ] T020 Confirm no public API change (no public symbol renamed) and that deprecated helpers still warn, then run the full suite

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Phase 1; blocks all stories (T003 renames the symbol every other task imports).
- **US1 (Phase 3)**: after T003/T005; T006–T009 touch different modules and can run in parallel.
- **US2 (Phase 4)**: after T003; touches only scrapy/pipelines/media.py, so T010–T013 are sequential within the file but parallel to Phase 3.
- **US3 (Phase 5)**: after the code changes it validates.
- **Polish (Phase 6)**: after all stories.

## Parallel Execution Example

```bash
Task: "T007 Replace the call in scrapy/core/spidermw.py"
Task: "T008 Replace the call in scrapy/core/downloader/middleware.py"
Task: "T009 Replace the call in scrapy/core/downloader/__init__.py"
```

## Implementation Strategy

1. MVP: Phase 2 + Phase 3 (callback delay removed) — validate with the callback-focused modules.
2. Increment 2: Phase 4 (media results) — validate with the media-focused modules.
3. Finish with Phase 5 and Phase 6 on both reactor configurations.

## Notes

- [P] tasks touch different files with no incomplete dependencies.
- No public API is renamed; `_defer_sleep_async`/`_process_pending_io` are private.
- Tests are not optional here only because T005 keeps the existing suite importable.
