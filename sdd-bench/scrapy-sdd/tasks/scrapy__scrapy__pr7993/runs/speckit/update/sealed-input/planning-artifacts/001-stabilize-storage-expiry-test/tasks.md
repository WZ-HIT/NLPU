---
description: "Task list for stabilizing the storage expiration test"
---

# Tasks: Stabilize Storage Expiry Test

**Input**: Design documents from `specs/001-stabilize-storage-expiry-test/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: This feature stabilizes an existing test. No production-code test tasks are planned, and tests must not run during this planning-only task.

**Organization**: The change is one independently verifiable test-stability story.

## Phase 1: Setup

**Purpose**: Confirm the bounded target and planning constraints.

- [ ] T001 Confirm the flaky scenario is `StorageTestMixin.test_storage` in `tests/test_downloadermiddleware_httpcache.py` and that no production files require changes.
- [ ] T002 Confirm the eventual change remains limited to `tests/test_downloadermiddleware_httpcache.py` and does not alter unrelated storage tests.

---

## Phase 2: Foundational

**Purpose**: Establish the deterministic timing model required by the story.

**CRITICAL**: Complete this phase before editing the shared test.

- [ ] T003 Identify the cache module time source used by `DbmCacheStorage._read_data` and `FilesystemCacheStorage._read_meta` in `scrapy/extensions/httpcache.py`; do not modify that file.
- [ ] T004 Define controlled reference-time values that make the first retrieval fresh and the second retrieval expired for both filesystem and DBM timestamp representations in `tests/test_downloadermiddleware_httpcache.py`.

**Checkpoint**: The timing sequence is deterministic and valid for every inherited storage variant.

---

## Phase 3: User Story 1 - Keep the pre-expiry assertion reliable (Priority: P1) 🎯 MVP

**Goal**: Ensure slow runners cannot turn the intended fresh-cache retrieval into an expired-cache miss.

**Independent Test**: Inspect and later execute the shared expiration scenario under injected pre-expiry delay; the first retrieval succeeds and the later retrieval misses only after time crosses the expiration threshold.

### Implementation for User Story 1

- [ ] T005 [US1] Update `StorageTestMixin.test_storage` in `tests/test_downloadermiddleware_httpcache.py` to use a controlled reference time when storing the response.
- [ ] T006 [US1] Keep the first retrieval and `assertEqualResponse` checks in `StorageTestMixin.test_storage` within the controlled fresh-time phase.
- [ ] T007 [US1] Advance the controlled reference time beyond `storage.expiration_secs` only after the fresh response checks and assert that the next retrieval returns `None` in `tests/test_downloadermiddleware_httpcache.py`.
- [ ] T008 [US1] Preserve the shared mixin inheritance so filesystem, gzip filesystem, DBM, and custom DBM classes all continue to exercise the stabilized test in `tests/test_downloadermiddleware_httpcache.py`.

**Checkpoint**: The shared expiration scenario is deterministic and fully exercises both fresh and expired states.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Verify scope and consistency without executing tests.

- [ ] T009 Review `tests/test_downloadermiddleware_httpcache.py` to confirm no sleeps, retries, or weakened assertions were introduced.
- [ ] T010 Review `git diff -- scrapy` to confirm production code and public behavior remain unchanged.
- [ ] T011 Update the implementation note in `specs/001-stabilize-storage-expiry-test/quickstart.md` only if the eventual implementation requires a materially different validation sequence.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Can start immediately.
- **Foundational (Phase 2)**: Depends on Setup and blocks all edits.
- **User Story 1 (Phase 3)**: Depends on Foundational.
- **Polish (Phase 4)**: Depends on User Story 1.

### Within User Story 1

- Establish the controlled time before changing retrieval assertions.
- Verify the fresh retrieval before advancing time.
- Advance time before asserting the expired miss.
- Confirm inherited coverage after the shared test is updated.

### Parallel Opportunities

- T001 and T002 can be performed together.
- T003 and T004 are analysis tasks and can be performed together.
- No implementation tasks are safely parallelizable because they modify the same test method.

## Parallel Example: Setup

```text
Task: "Confirm StorageTestMixin.test_storage in tests/test_downloadermiddleware_httpcache.py"
Task: "Confirm scope remains limited to tests/test_downloadermiddleware_httpcache.py"
```

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2.
2. Complete User Story 1.
3. Review the diff and the deterministic timing sequence.
4. Stop before running tests because that execution is outside this planning task.

### Incremental Delivery

1. Deliver the controlled-time update to the shared test.
2. Confirm inherited storage-variant coverage remains intact.
3. Confirm production behavior and unrelated tests are untouched.

## Notes

- The actual PR is expected to be test-only.
- Do not run tests as part of this Detect planning phase.
- Do not modify production code or tests while producing these planning artifacts.
