# Tasks: Bootstrap Error Exit Codes

**Input**: Planning documents in this directory

## Phase 1: Setup

- [ ] T001 Confirm the existing exit-code behavior in `scrapy/commands/crawl.py` and `scrapy/commands/runspider.py`
- [ ] T002 Identify the command-level test harness in `tests/utils/cmdline.py`

## Phase 2: Foundational

- [ ] T003 Confirm `CrawlerProcess.bootstrap_failed` is available after `start()` in `scrapy/crawler.py`

## Phase 3: User Story 1 - Failed Startup Detection (Priority: P1)

**Goal**: Return status `1` when bootstrap fails.

**Independent Test**: Invoke each affected command in a bootstrap-failure fixture and assert status `1`.

- [ ] T004 [P] [US1] Add bootstrap-failure exit-code coverage to `tests/test_command_check.py`
- [ ] T005 [P] [US1] Add bootstrap-failure exit-code coverage to `tests/test_command_parse.py`
- [ ] T006 [P] [US1] Add bootstrap-failure exit-code coverage to `tests/test_command_fetch.py`
- [ ] T007 [US1] Set `self.exitcode = 1` on bootstrap failure in `scrapy/commands/check.py`
- [ ] T008 [US1] Set `self.exitcode = 1` on bootstrap failure in `scrapy/commands/parse.py`
- [ ] T009 [US1] Set `self.exitcode = 1` on bootstrap failure in `scrapy/commands/fetch.py`

## Phase 4: User Story 2 - Successful Behavior Preservation (Priority: P2)

**Goal**: Preserve status `0` for successful runs and status `2` for usage errors.

**Independent Test**: Re-run existing success and invalid-argument tests for the affected commands.

- [ ] T010 [US2] Verify successful command tests remain green in `tests/test_command_check.py`
- [ ] T011 [US2] Verify successful and usage-error tests remain green in `tests/test_command_parse.py`
- [ ] T012 [US2] Verify successful and usage-error tests remain green in `tests/test_command_fetch.py`

## Phase 5: Polish

- [ ] T013 Review `detection-draft.json` for repository-relative paths and required fields

## Dependencies

User Story 1 is the MVP. User Story 2 validates regressions after User Story 1.

## Parallel Execution

T004, T005, and T006 operate on separate test files and may run in parallel. T007-T009
operate on separate command modules and may run in parallel.
