# Tasks: Fix open_in_browser base insertion without a head

**Input**: Design documents from `/workspace/specs/001-fix-open-in-browser-base/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: Regression coverage is required for this bug fix; no tests are run during this planning phase.

## Phase 1: Setup

**Purpose**: Establish the exact affected behavior and verification scope.

- [ ] T001 Review current browser-preview behavior and existing cases in `tests/test_utils_response.py`
- [ ] T002 [P] Review the consumer path in `scrapy/commands/view.py` and `tests/test_commands.py`

---

## Phase 2: Foundational

**Purpose**: Establish the compatibility constraints that all implementation work must preserve.

- [ ] T003 Confirm the insertion branch preserves comments, existing bases, text responses, and malformed-input performance
- [ ] T004 Confirm the public signature and return behavior of `open_in_browser` in `scrapy/utils/response.py` remain unchanged

**Checkpoint**: The behavior contract is clear and no implementation changes are needed before the regression case exists.

---

## Phase 3: User Story 1 - Preview HTML without a head (Priority: P1) 🎯 MVP

**Goal**: Ensure headless HTML receives one effective base URL in browser preview.

**Independent Test**: Prepare a headless HTML response with a capturing opener and verify the captured output contains exactly one base element with the response URL.

### Tests for User Story 1

- [ ] T005 [P] [US1] Add a headless-HTML regression case in `tests/test_utils_response.py`
- [ ] T006 [P] [US1] Extend the head-insertion coverage in `tests/test_utils_response.py` to preserve existing-head behavior

### Implementation for User Story 1

- [ ] T007 [US1] Add the headless fallback in `scrapy/utils/response.py` (depends on T005)
- [ ] T008 [US1] Preserve the existing in-head insertion path in `scrapy/utils/response.py` (depends on T007)

**Checkpoint**: Headless and normal HTML previews both resolve relative resources correctly.

---

## Phase 4: User Story 2 - Preserve preview safety and compatibility (Priority: P2)

**Goal**: Prevent duplicate bases, content loss, text regressions, and malformed-input performance regressions.

**Independent Test**: Run the existing comments, base-present, text-response, unsupported-type, and malformed-input checks after the fallback change.

### Tests for User Story 2

- [ ] T009 [P] [US2] Extend comment and existing-base coverage in `tests/test_utils_response.py`
- [ ] T010 [P] [US2] Extend malformed head-like input coverage in `tests/test_utils_response.py`

### Implementation for User Story 2

- [ ] T011 [US2] Refine fallback logic in `scrapy/utils/response.py` to avoid duplicate insertion (depends on T009)
- [ ] T012 [US2] Verify text and unsupported response paths remain unchanged in `scrapy/utils/response.py` (depends on T011)

**Checkpoint**: Existing preview behavior and safety checks remain intact.

---

## Final Phase: Polish & Cross-Cutting Concerns

- [ ] T013 [P] Update user-facing release notes in `docs/news.rst`
- [ ] T014 Run the focused checks described in `quickstart.md`
- [ ] T015 Review the final diff for unchanged public behavior in `scrapy/utils/response.py` and `tests/test_utils_response.py`

---

## Dependencies & Execution Order

- Setup (T001-T002) has no dependencies.
- Foundational work (T003-T004) depends on setup.
- User Story 1 (T005-T008) depends on foundational work.
- User Story 2 (T009-T012) depends on User Story 1 because it hardens the same insertion path.
- Polish (T013-T015) depends on both stories.

## Parallel Opportunities

- T001 and T002 can run in parallel.
- T005 and T006 can run in parallel while editing separate test cases within the same file only if coordinated.
- T009 and T010 can run in parallel after the core fallback is understood.
- T013 can run independently after the behavior is fixed.

## Implementation Strategy

Deliver User Story 1 as the MVP, then harden compatibility in User Story 2. The direct test module is the primary regression target; the command test is useful end-to-end context but is not required for the first fix.
