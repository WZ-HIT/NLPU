---

description: "Task list for making test_file_path_from_response deterministic across platforms"
---

# Tasks: Deterministic Response-Based File Path Test

**Input**: Design documents from `specs/001-fix-clock-resolution-flake/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: No new tests are requested. This feature *is* a test fix, so the
"test" work is the change to the existing test in
`tests/test_pipeline_files.py`; no new test files are added.

**Organization**: Tasks are grouped by user story so each story can be
implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- Single project: `scrapy/` and `tests/` at the repository root.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the target module, helpers, and base state before editing.

- [ ] T001 Confirm the target test lives at `tests/test_pipeline_files.py::TestFilesPipeline::test_file_path_from_response` and record the current mocked store timestamp (`time.time()`) used for `last_modified`.
- [ ] T002 [P] Confirm the helpers reused by the test (`_create_pipeline`, `_prepare_request_object`, `_create_item_with_files`) and the mocks (`mocked_download_func` in `tests/utils/media_pipelines.py`, `coroutine_test` in `tests/utils/decorators.py`) in `tests/test_pipeline_files.py`.
- [ ] T003 [P] Confirm the production code path stays untouched: read `scrapy/pipelines/files.py` (`_onsuccess`, `file_path`) and `scrapy/pipelines/media.py` (`media_to_download`) only as reference.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Agree on the determinism invariant that all story work depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T004 Document the determinism invariant for the mocked store record: with `FILES_EXPIRES = 0`, the computed age must be strictly greater than the expiry for any realistic wall-clock reading, so the freshness check cannot resolve to `uptodate`.
- [ ] T005 [P] Identify every place in `tests/test_pipeline_files.py` where the mocked `stat_file` timestamp is derived from the live clock, so the fix does not miss a second occurrence.

**Checkpoint**: The invariant and the exact edit sites are known - user story work can begin.

---

## Phase 3: User Story 1 - Deterministic verdict for a response-based file path (Priority: P1) 🎯 MVP

**Goal**: The response-based file path test always reports `downloaded` with a `.pdf` path, regardless of host clock resolution.

**Independent Test**: `pytest tests/test_pipeline_files.py::TestFilesPipeline::test_file_path_from_response` passes repeatedly, including on a coarse-clock platform, with no sleep or retry.

### Implementation for User Story 1

- [ ] T006 [US1] Replace the live-clock `last_modified` seeded into the mocked `FSFilesStore.stat_file` with a value that is unambiguously in the past, inside `test_file_path_from_response` in `tests/test_pipeline_files.py`.
- [ ] T007 [US1] Verify the edit keeps `FILES_EXPIRES = 0` and the response-aware `ContentTypeFilesPipeline.file_path` override intact in `tests/test_pipeline_files.py`.
- [ ] T008 [US1] Confirm the three assertions in the test (`status == "downloaded"`, path ends with `.pdf`, stored bytes equal the mocked payload) are unchanged in `tests/test_pipeline_files.py`, per `contracts/test-contract.md`.
- [ ] T009 [US1] Confirm the change introduces no sleep, retry, polling, or tolerant assertion (FR-004) in `tests/test_pipeline_files.py`.

**Checkpoint**: User Story 1 is fully functional and independently verifiable.

---

## Phase 4: User Story 2 - No regression in the neighbouring pipeline tests (Priority: P2)

**Goal**: The surrounding files-pipeline module and adjacent pipeline modules still pass.

**Independent Test**: `pytest tests/test_pipeline_files.py` passes fully; adjacent modules behave as before.

### Implementation for User Story 2

- [ ] T010 [P] [US2] Review `tests/test_pipeline_files.py` for shared helper or mock changes that could affect sibling tests such as `test_file_path`, `test_file_path_from_item`, and the expiry tests.
- [ ] T011 [P] [US2] Review `tests/test_pipeline_media.py` and `tests/test_pipeline_images.py`, which share the `stat_file`/freshness code path via `scrapy/pipelines/media.py` and the `ImagesPipeline` subclass.
- [ ] T012 [US2] Review `tests/test_pipeline_crawl.py` integration coverage of the files pipeline for assumptions about file paths or freshness.

**Checkpoint**: Both user stories are satisfied; the fix is local and non-regressive.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final hygiene for the change.

- [ ] T013 Document why the timestamp is no longer derived from the live clock, in the docstring or an inline comment of `test_file_path_from_response` in `tests/test_pipeline_files.py`.
- [ ] T014 [P] Confirm no file under `scrapy/` was modified by the change (`git status`).
- [ ] T015 Confirm `quickstart.md` scenarios match the final behavior and that the diff contains no unrelated edits.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational completion.
- **User Story 2 (Phase 4)**: Depends on Foundational completion; its review tasks also depend on T006 landing.
- **Polish (Phase 5)**: Depends on User Story 1 and User Story 2 completion.

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies on other stories.
- **User Story 2 (P2)**: Review work can start after Foundational, but its
  confirmation depends on the User Story 1 edit being in place.

### Within Each User Story

- Implement the local change before validating assertions.
- Validate the invariant before moving to regression review.

### Parallel Opportunities

- T002 and T003 can run in parallel (different files).
- T010, T011, and T012 can run in parallel (different test modules).
- T014 can run in parallel with T015.

---

## Parallel Example: User Story 2

```bash
Task: "Review tests/test_pipeline_files.py sibling tests for shared-helper impact"
Task: "Review tests/test_pipeline_media.py and tests/test_pipeline_images.py for freshness-path impact"
Task: "Review tests/test_pipeline_crawl.py integration assumptions about file paths"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (the determinism invariant).
3. Complete Phase 3: User Story 1 - the single-line timestamp change.
4. **STOP and VALIDATE**: run the target test repeatedly and confirm a stable
   `downloaded` outcome.

### Incremental Delivery

1. Setup + Foundational → edit sites known.
2. User Story 1 → determinism fix lands → validate independently.
3. User Story 2 → regression review of adjacent modules.
4. Polish → documentation and diff hygiene.

---

## Notes

- [P] tasks touch different files and have no dependencies.
- This planning stage performs no test execution and modifies no project code
  or tests; the tasks above are for the later implementation stage.
- The change is intentionally confined to the data seeded into the mocked
  store in `tests/test_pipeline_files.py`.
