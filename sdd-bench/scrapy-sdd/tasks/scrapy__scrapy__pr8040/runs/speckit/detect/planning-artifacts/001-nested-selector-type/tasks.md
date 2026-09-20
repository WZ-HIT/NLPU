# Tasks: Nested Selector Type Inference

**Input**: Design documents from `/specs/001-nested-selector-type/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

## Phase 1: Setup

- [ ] T001 Confirm the selector constructor and existing regression tests in scrapy/selector/unified.py and tests/test_selector.py

## Phase 2: Foundational

No shared infrastructure is required.

## Phase 3: User Story 1 - Preserve Parsel Inference for Nested Results (Priority: P1) 🎯 MVP

**Goal**: Let parsel determine the type of a selector constructed from an existing root.

**Independent Test**: Construct a selector from a nested JSON scalar root with no explicit type and verify that parsel infers JSON.

- [ ] T002 [US1] Add regression coverage for nested root-based selector type inference in tests/test_selector.py
- [ ] T003 [US1] Restrict response-derived type defaults to omitted-root construction in scrapy/selector/unified.py
- [ ] T004 [US1] Verify the focused selector tests in tests/test_selector.py without changing unrelated tests

## Phase 4: User Story 2 - Preserve Response-Based Defaults (Priority: P2)

**Goal**: Keep top-level response-derived selector behavior unchanged.

**Independent Test**: Exercise HTML, XML, JSON, and general response selector construction and verify the existing inferred types.

- [ ] T005 [US2] Run the response-specific flavor-detection tests in tests/test_selector.py
- [ ] T006 [US2] Confirm explicit selector types still override inference in tests/test_selector.py

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T007 Run the repository's selector test module in tests/test_selector.py and review any failures
- [ ] T008 Review documentation impact in docs/topics/selectors.rst and update it only if the public behavior description is incomplete

## Dependencies & Execution Order

- T001 precedes T002-T008.
- T002 must fail before T003 is implemented.
- T003 requires T002.
- T004 depends on T002 and T003.
- T005-T006 validate the P2 compatibility story.
- T007-T008 follow implementation and focused validation.

## Parallel Opportunities

- T002 and T005 can be prepared in parallel because they describe distinct test cases in the same module, but edits to that module must be serialized.

## Implementation Strategy

Implement the P1 fix first, verify nested inference and response defaults in `tests/test_selector.py`, then run the focused selector module. Keep the change limited to selector construction and regression coverage.
