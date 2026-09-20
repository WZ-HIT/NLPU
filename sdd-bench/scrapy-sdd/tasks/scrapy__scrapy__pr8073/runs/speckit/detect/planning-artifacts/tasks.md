# Tasks: Re-enable DirtyReactorAggregateError Tests

**Input**: Design documents in `specs/`

**Prerequisites**: plan.md and spec.md

## Phase 1: Setup

- [ ] T001 Confirm the three Windows-asyncio skip locations and their test symbols in `tests/test_downloader_handler_twisted_ftp.py` and `tests/utils/bases/download_handlers_http.py`
- [ ] T002 Confirm that no runtime code change is required by the feature specification

## Phase 2: User Story 1 - Restore Cross-Platform Coverage (Priority: P1)

**Goal**: Re-enable all tests currently skipped because of `DirtyReactorAggregateError`.

**Independent Test**: The affected tests are collected and pass when the Windows asyncio
configuration is used.

- [ ] T003 [US1] Remove the Windows-asyncio skip guard from `TestFTP.test_invalid_credentials` in `tests/test_downloader_handler_twisted_ftp.py`
- [ ] T004 [US1] Remove the Windows-asyncio skip guard from `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd` in `tests/utils/bases/download_handlers_http.py`
- [ ] T005 [US1] Remove the Windows-asyncio skip guard from `TestHttpBase.test_timeout_download_from_spider_server_hangs` in `tests/utils/bases/download_handlers_http.py`
- [ ] T006 [US1] Verify the three tests execute without changing their existing assertions

## Phase 3: Polish & Cross-Cutting Concerns

- [ ] T007 Review the diff to ensure no product code or unrelated tests changed
- [ ] T008 Run the targeted tests on Windows with the asyncio reactor and on at least one non-asyncio reactor configuration

## Dependencies & Execution Order

- T001-T002 precede T003-T005.
- T003-T005 are independent edits in two files.
- T006 depends on T003-T005.
- T007-T008 follow T006.

## Implementation Strategy

Apply the minimal test-only diff, validate the previously skipped paths first, then run the
affected module-level matrix to detect regressions.
