---

description: "Task list for re-enabling DirtyReactorAggregateError tests"
---

# Tasks: Re-enable DirtyReactorAggregateError Tests

**Input**: Design documents from `/workspace/specs/`

**Prerequisites**: spec.md, plan.md, research.md, data-model.md

**Tests**: Detection only; do not execute tests or modify tests in this stage.

## Phase 1: Setup

- [ ] T001 Confirm the base commit and read `/task-input/task.md` at repository root
- [ ] T002 [P] Confirm `/workspace/specs` is the writable planning directory in `/workspace`
- [ ] T003 [P] Record the read-only constraints and forbidden test execution in `/workspace/specs/plan.md`

## Phase 2: Foundational Detection

- [ ] T004 Search `tests/` for the exact `DirtyReactorAggregateError` marker
- [ ] T005 [P] Inspect each match in `tests/test_downloader_handler_twisted_ftp.py` and identify the enclosing test symbol
- [ ] T006 [P] Inspect each match in `tests/utils/bases/download_handlers_http.py` and identify the enclosing test symbols
- [ ] T007 Reconcile the match set and confirm no additional markers exist under `tests/`

## Phase 3: User Story 1 - Restore Full Test Coverage (P1)

**Goal**: Produce the candidate test-file draft for later re-enablement.

**Independent Test**: Parse `detection-draft.json` and verify its only key is
`candidates`, each candidate has exactly `path`, `symbols`, and `reason`, and
each listed path exists under `tests/`.

- [ ] T008 [US1] Add `tests/test_downloader_handler_twisted_ftp.py` with symbol `TestFTP.test_invalid_credentials` in `/workspace/specs/detection-draft.json`
- [ ] T009 [US1] Add `tests/utils/bases/download_handlers_http.py` with symbols `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd` and `TestHttpBase.test_timeout_download_from_spider_server_hangs` in `/workspace/specs/detection-draft.json`
- [ ] T010 [US1] Validate that `/workspace/specs/detection-draft.json` contains only a `candidates` array and all paths are repository-relative test paths

## Phase 4: Polish and Verification

- [ ] T011 [P] Confirm `/workspace/specs/spec.md`, `plan.md`, `research.md`, `data-model.md`, and `quickstart.md` are present
- [ ] T012 Confirm exactly one `detection-draft.json` exists under `/workspace/specs`
- [ ] T013 Confirm no files under `/workspace/scrapy` or `/workspace/tests` were modified
- [ ] T014 Confirm no tests were executed and no generated cache or test output exists under the planning directory

## Dependencies & Execution Order

- Phase 1 has no dependencies.
- Phase 2 depends on the planning mount and read-only search.
- Phase 3 depends on the reconciled marker set from Phase 2.
- Phase 4 depends on all prior phases.

## Parallel Opportunities

- T002 and T003 can run together.
- T005 and T006 can run together.
- T011 can run while the final detection checks are reviewed.

## Implementation Strategy

1. Reconcile the exact marker occurrences.
2. Draft the candidate records without modifying tests.
3. Validate the JSON shape, path prefixes, and repository cleanliness.
4. Hand the draft to the update stage for any re-enablement decision.
