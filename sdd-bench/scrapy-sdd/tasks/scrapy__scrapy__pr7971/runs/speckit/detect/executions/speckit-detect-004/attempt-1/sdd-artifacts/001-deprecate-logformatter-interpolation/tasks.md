# Tasks: Deprecate Log Formatter Message Interpolation With the Returned Dict

## Phase 1: Setup

- [ ] T001 Confirm the current behavior of `logformatter_adapter` in `scrapy/utils/log.py` against `tests/test_utils_log.py::TestLogformatterAdapter`
- [ ] T002 Confirm Scrapy deprecation-warning conventions in `scrapy/utils/deprecate.py` and `tests/test_utils_deprecate.py`

## Phase 2: Foundational

- [ ] T003 [P] Add a reusable legacy-result fixture/helper to `tests/test_utils_log.py` for results that omit `args`
- [ ] T004 [P] Document the deprecated dict-interpolation path in `docs/news.rst`

## Phase 3: User Story 1 - Legacy custom log formatters keep working with a warning (P1)

**Goal**: Restore dict-based interpolation for legacy results and warn about it.

**Independent Test**: Adapter test with a result that omits `args` renders the
interpolated message and records one deprecation warning.

- [ ] T005 [P] [US1] Add a failing test for the legacy dict-interpolation result in `tests/test_utils_log.py`
- [ ] T006 [US1] Implement the deprecation warning and dict-mapping fallback in `scrapy/utils/log.py`
- [ ] T007 [US1] Cover placeholder-free legacy messages and missing keys in `tests/test_utils_log.py`

## Phase 4: User Story 2 - Explicit `args` remains the supported contract (P2)

**Goal**: Keep mapping and tuple `args` behavior warning-free and unchanged.

**Independent Test**: Existing adapter tests for mapping and tuple args pass with
no warnings.

- [ ] T008 [P] [US2] Assert no deprecation warning for explicit mapping and tuple `args` in `tests/test_utils_log.py`
- [ ] T009 [P] [US2] Verify default `LogFormatter` method results still satisfy the contract in `tests/test_logformatter.py`
- [ ] T010 [US2] Verify suppressed (`None`) formatter results remain skipped in `tests/test_logformatter.py`

## Phase 5: Polish

- [ ] T011 [P] Update the `LogFormatter` documentation in `docs/topics/logging.rst` to describe explicit `args`
- [ ] T012 [P] Add a typing/regression check for the adapter signature in `tests_typing/` if the project requires one
- [ ] T013 Run the focused tests in `tests/test_utils_log.py` and `tests/test_logformatter.py` and confirm the stated success criteria

## Dependencies

- T005 depends on T003.
- T006 depends on T005.
- T007 depends on T006.
- T008, T009, and T010 depend on T006.
- T013 depends on all implementation and test tasks.

## Parallel Execution Examples

- T003 and T004 can run in parallel.
- T008, T009, and T010 touch different assertions/files and can run in parallel.
- T011 and T012 can run in parallel once T006 is complete.

## Implementation Strategy

Deliver User Story 1 first: it is the backward-compatibility fix and the MVP.
Then lock in User Story 2 regressions so the deprecation cannot double-format or
warn on the supported paths. Documentation and typing polish follow.
