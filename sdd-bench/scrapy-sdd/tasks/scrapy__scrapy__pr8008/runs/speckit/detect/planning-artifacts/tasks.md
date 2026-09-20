# Tasks: Stabilize Slow-Pipeline Spider-Start Test

**Input**: Design documents from `/workspace/specs/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`

**Tests**: Test changes are required because the requested work repairs a test defect.

## Phase 1: Setup

**Purpose**: Confirm the exact regression boundary.

- [ ] T001 Confirm the base revision and affected test module in `tests/test_spider_start.py`
- [ ] T002 Review existing ordered assertions and signals usage in `tests/test_spider_start.py`

---

## Phase 2: Foundational

**Purpose**: Preserve current behavior before introducing an optional comparison mode.

- [ ] T003 [P] Document that `_test_spider` must remain order-sensitive by default in `tests/test_spider_start.py`
- [ ] T004 [P] Confirm the slow-pipeline assertion must retain exact item cardinality and contents in `tests/test_spider_start.py`

**Checkpoint**: The compatibility boundary is clear and all non-slow-pipeline callers remain ordered.

---

## Phase 3: User Story 1 - Trust the slow-pipeline regression test (Priority: P1) 🎯 MVP

**Goal**: Accept either item completion order without weakening the assertion.

**Independent Test**: Run `test_slow_pipeline` repeatedly and verify that it passes for either order, then verify it still fails when an expected item is missing or changed.

- [ ] T005 [US1] Add an `ordered: bool = True` option to `_test_spider` in `tests/test_spider_start.py`
- [ ] T006 [US1] Keep the existing sequence equality assertion when `ordered` is true in `tests/test_spider_start.py`
- [ ] T007 [US1] Add a hashability-safe multiset comparison for `ordered=False` in `tests/test_spider_start.py`
- [ ] T008 [US1] Pass `ordered=False` from `test_slow_pipeline` in `tests/test_spider_start.py`

**Checkpoint**: The slow-pipeline test is deterministic with respect to item completion order and still detects content/cardinality regressions.

---

## Phase 4: Polish

**Purpose**: Validate compatibility and scope.

- [ ] T009 Verify every other `_test_spider` caller relies on the default ordered behavior in `tests/test_spider_start.py`
- [ ] T010 Verify no production modules or public APIs changed

---

## Dependencies & Execution Order

- Setup precedes implementation.
- Foundational review precedes the helper change.
- T005 must precede T006, T007, and T008.
- T009 and T010 follow the implementation.

## Parallel Opportunities

- T003 and T004 can be reviewed together.
- T009 and T010 can be checked independently after implementation.

## Implementation Strategy

Complete the single P1 story as the MVP, then verify that the helper's default preserves all existing ordered tests.
