---
description: "Task list for typing spider-related test modules"
---

# Tasks: Typed Spider Test Modules

**Input**: Design documents from `/specs/001-type-spider-test-modules/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Not requested as new work — the change is annotation-only, so the existing test modules
are the verification surface (no new test files are created).

**Organization**: Tasks are grouped by user story. Story phases may run in parallel per file because
each task touches a different module.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the working inventory before editing

- [ ] T001 Inventory the in-scope modules and their symbols from `tests/spiders.py`, `tests/utils/bases/spider.py`, `tests/test_spider.py`, `tests/test_spider_crawl.py`, `tests/test_spider_sitemap.py`, `tests/test_spidermiddleware_output_chain.py`, `tests/test_spidermiddleware_process_start.py`
- [ ] T002 Record the pre-change collected-test baseline for the in-scope modules (identifiers and outcomes) as described in `specs/001-type-spider-test-modules/quickstart.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared annotation targets that other modules depend on

**⚠️ CRITICAL**: T003 and T004 unblock the story phases, because test modules inherit from them

- [ ] T003 [P] Add parameter/return annotations to the spider fixture classes in `tests/spiders.py`
- [ ] T004 [P] Add parameter/return annotations to `TestSpiderBase` and its methods in `tests/utils/bases/spider.py`

**Checkpoint**: Shared fixtures and the spider test base class are annotated and importable unchanged

---

## Phase 3: User Story 1 - Static analysis covers spider test code (Priority: P1) 🎯 MVP

**Goal**: Every in-scope module has explicit annotations and passes strict checking without a
per-module untyped-definition exclusion.

**Independent Test**: Remove the in-scope exclusion entries and run strict static analysis — zero
errors for those modules.

### Implementation for User Story 1

- [ ] T005 [P] [US1] Add parameter/return annotations to test classes and helpers in `tests/test_spider.py`
- [ ] T006 [P] [US1] Add parameter/return annotations to `TestCrawlSpider`, `TestDeprecation`, and helpers in `tests/test_spider_crawl.py`
- [ ] T007 [P] [US1] Add parameter/return annotations to `TestSitemapSpider`, `RawSitemapSpider`, and helpers in `tests/test_spider_sitemap.py`
- [ ] T008 [P] [US1] Add parameter/return annotations to `TestSpiderMiddleware` and the spider/middleware helper classes in `tests/test_spidermiddleware_output_chain.py`
- [ ] T009 [P] [US1] Add parameter/return annotations to `TestMain`, the sleep/wrap middlewares, and spider helpers in `tests/test_spidermiddleware_process_start.py`
- [ ] T010 [US1] Remove the in-scope module entries from the untyped-definition exclusion block in `pyproject.toml` (depends on T003–T009)
- [ ] T011 [US1] Run strict static analysis over the repository and resolve any remaining errors in the in-scope modules (depends on T010)

**Checkpoint**: Static analysis covers all in-scope spider test modules

---

## Phase 4: User Story 2 - Behaviour is unchanged for test execution (Priority: P2)

**Goal**: The annotated modules execute identically to the pre-change baseline.

**Independent Test**: Compare collected test identifiers and outcomes against the T002 baseline.

### Implementation for User Story 2

- [ ] T012 [US2] Re-run the in-scope modules' tests and compare collected test identifiers with the T002 baseline
- [ ] T013 [US2] Compare pass/fail/skip outcomes with the T002 baseline and fix any divergence caused by an annotation in `tests/` (depends on T012)

**Checkpoint**: Behaviour parity is demonstrated for the affected test modules

---

## Phase 5: User Story 3 - Reviewable, low-risk annotation-only diff (Priority: P3)

**Goal**: The diff contains only annotations, typing-only imports, and exclusion bookkeeping.

**Independent Test**: Review the diff of the in-scope modules and confirm no runtime statement changed.

### Implementation for User Story 3

- [ ] T014 [P] [US3] Run the project's lint/format checks over the changed files in `tests/`
- [ ] T015 [US3] Audit the diff of `tests/spiders.py`, `tests/utils/bases/spider.py`, and the five in-scope test modules for non-annotation changes
- [ ] T016 [US3] Confirm every inline suppression introduced is limited to intentionally-invalid-call tests and is self-explanatory (depends on T015)

**Checkpoint**: Review confirms an annotation-only change

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Planning-artifact and detection hygiene

- [ ] T017 Validate `specs/detection-draft.json` against `specs/001-type-spider-test-modules/contracts/detection-draft.schema.json`
- [ ] T018 Re-run the validation scenarios listed in `specs/001-type-spider-test-modules/quickstart.md`
- [ ] T019 Verify no unrelated static-analysis exclusion entry was removed from `pyproject.toml` (FR-008)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup — blocks the story phases.
- **User Stories (Phase 3+)**: Depend on Foundational; US1 must complete before US2/US3 verification is
  meaningful.
- **Polish (Phase 6)**: Depends on the desired stories being complete.

### User Story Dependencies

- **US1 (P1)**: After Phase 2. No dependency on other stories.
- **US2 (P2)**: After US1 (needs the annotated modules to compare against the baseline).
- **US3 (P3)**: After US1 (needs the diff to exist). Independent of US2.

### Within Each User Story

- Annotation tasks precede exclusion-list removal and static-analysis execution.
- Behaviour-parity comparison precedes any corrective edit.

### Parallel Opportunities

- T003 and T004 are parallel (different files).
- T005–T009 are parallel (different files) once Phase 2 completes.
- T014 can run alongside T012/T013.

---

## Parallel Example: User Story 1

```text
Task: "Add parameter/return annotations to tests/test_spider.py"
Task: "Add parameter/return annotations to tests/test_spider_crawl.py"
Task: "Add parameter/return annotations to tests/test_spider_sitemap.py"
Task: "Add parameter/return annotations to tests/test_spidermiddleware_output_chain.py"
Task: "Add parameter/return annotations to tests/test_spidermiddleware_process_start.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 (US1) — this alone delivers the feature's value.
3. **STOP and VALIDATE**: strict static analysis passes with the exclusions removed.

### Incremental Delivery

1. Phase 1 + Phase 2 → shared fixtures/base class annotated.
2. US1 → modules annotated, exclusion entries removed, static analysis green.
3. US2 → behaviour parity demonstrated.
4. US3 → diff reviewed as annotation-only.
5. Polish → planning and detection artifacts validated.

---

## Notes

- [P] tasks touch different files and have no dependencies on incomplete tasks.
- Every task names an exact repository-relative file path.
- This feature intentionally adds no new test files; the existing spider tests are the verification
  surface.
