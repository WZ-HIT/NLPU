# Tasks: Open-in-Browser ReDoS Test Stability

**Input**: Design documents from `/workspace/specs/`

**Prerequisites**: plan.md, spec.md, research.md, quickstart.md

**Tests**: The feature itself modifies tests. No separate test-generation work is required.

**Organization**: The work is grouped under the single P1 user story.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the exact regression surface before editing.

- [ ] T001 Confirm that `tests/test_utils_response.py` contains only the two open-in-browser timing-sensitive regression checks relevant to PR 7995.
- [ ] T002 Record the existing 20 ms CPU allowance and pathological inputs from `tests/test_utils_response.py` as the baseline that must be preserved or intentionally replaced.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish a validation method that distinguishes slow normal execution from catastrophic execution.

- [ ] T003 Define the slow-interpreter or constrained-CPU validation environment for `tests/test_utils_response.py`, without adding dependencies to the project.
- [ ] T004 Define a finite, environment-tolerant runtime guard for `tests/test_utils_response.py` that can still detect catastrophic processing.

**Checkpoint**: The revised guard criteria are understood before modifying either regression check.

---

## Phase 3: User Story 1 - Reliable ReDoS Regression Checks (Priority: P1) 🎯 MVP

**Goal**: Make the two open-in-browser ReDoS checks reliable on slow interpreters while preserving their regression signal.

**Independent Test**: Run the two targeted checks on a slow interpreter and confirm they pass, then exercise a vulnerable implementation and confirm they fail.

### Implementation for User Story 1

- [ ] T005 [US1] Update `test_open_in_browser_redos_comment` in `tests/test_utils_response.py` to use the environment-tolerant guard while retaining its pathological comment input.
- [ ] T006 [US1] Update `test_open_in_browser_redos_head` in `tests/test_utils_response.py` to use the environment-tolerant guard while retaining its pathological head input.
- [ ] T007 [US1] Confirm neither change skips, removes, or unconditionally xfails a regression check in `tests/test_utils_response.py`.
- [ ] T008 [US1] Validate both targeted checks on normal and slow interpreters in `tests/test_utils_response.py` and confirm the expected pass/fail behavior.

**Checkpoint**: User Story 1 is complete when both checks are stable under normal linear processing and still sensitive to catastrophic processing.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Confirm scope discipline and repository compatibility.

- [ ] T009 Run the complete `tests/test_utils_response.py` module and confirm no unrelated regression.
- [ ] T010 Review the final diff and confirm it contains no production-code or unrelated test changes.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks the user story.
- **User Story 1 (Phase 3)**: Depends on Foundational.
- **Polish (Phase 4)**: Depends on User Story 1.

### Within User Story 1

- T005 and T006 modify different test functions but the same file, so they should be edited sequentially to avoid conflicting changes.
- T007 and T008 follow both edits.

### Parallel Opportunities

- T001 and T002 are read-only and may be performed together.
- T003 and T004 can be evaluated together because both concern the validation strategy.
- T009 and T010 may run after all edits are complete; T009 produces runtime evidence and T010 reviews scope.

---

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2.
2. Complete T005-T008 for the two affected checks.
3. Validate slow-interpreter stability and regression sensitivity before considering the task complete.

### Incremental Delivery

1. Stabilize the comment-removal check.
2. Stabilize the head-search check.
3. Validate both checks together.
4. Review the complete test module and diff for scope discipline.

---

## Notes

- Do not modify `scrapy/utils/response.py` unless implementation evidence proves a production defect.
- Keep the existing test names so downstream selection and detection remain stable.
- The planning phase itself does not execute tests or edit project source.
