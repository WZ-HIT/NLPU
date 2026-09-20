# Tasks: Download Delay Crawl Coverage

**Input**: `spec.md`, `plan.md`, `research.md`, `data-model.md`

**Tests**: This feature changes tests; no additional test-first implementation is needed.

## Phase 1: Setup

- [ ] T001 Confirm the detected file and symbols in `tests/test_crawl.py`
- [ ] T002 Confirm no production source changes are needed

## Phase 2: Foundational

- [ ] T003 Inspect timing collection in `tests/spiders.py::FollowAllSpider`
- [ ] T004 Confirm the mock follow resource can serve enough pages

## Phase 3: User Story 1 - Fixed delay (Priority: P1)

- [ ] T005 [US1] Increase the fixed-delay crawl page count in `tests/test_crawl.py::TestCrawl::test_fixed_delay`
- [ ] T006 [US1] Keep the delayed assertion and no-delay control in `tests/test_crawl.py::TestCrawl::_test_delay`

## Phase 4: User Story 2 - Randomized delay (Priority: P2)

- [ ] T007 [US2] Increase the randomized-delay crawl page count in `tests/test_crawl.py::TestCrawl::test_randomized_delay`
- [ ] T008 [US2] Preserve the wider randomized tolerance in `tests/test_crawl.py::TestCrawl::_test_delay`

## Phase 5: Polish

- [ ] T009 Review the final diff to ensure only test files changed
- [ ] T010 Run the focused tests when implementation is authorized

## Dependencies & Execution Order

T001-T004 precede story work. US1 and US2 can proceed independently after foundational checks. T009-T010 follow both stories.

## MVP Scope

User Story 1: fixed-delay coverage with multiple pages and the no-delay control.
