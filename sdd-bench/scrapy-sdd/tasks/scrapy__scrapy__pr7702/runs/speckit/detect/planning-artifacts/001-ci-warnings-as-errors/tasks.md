# Tasks: CI Warnings as Errors

**Input**: Design documents from `/specs/001-ci-warnings-as-errors/`

## Phase 1: Setup

- [ ] T001 Record the current warning filters in `pyproject.toml` and enumerate warning-sensitive test paths.

## Phase 2: Foundational

- [ ] T002 Add the global warning-to-error base filter in `pyproject.toml` while preserving existing narrow exceptions.
- [ ] T003 Confirm local `pytest.warns`, `pytest.mark.filterwarnings`, and `warnings.catch_warnings` usage can override the global policy.

## Phase 3: User Story 1 - Fail on unexpected warnings (Priority: P1)

**Goal**: Every unexpected warning fails the responsible test.

**Independent Test**: Run one intentionally warning-emitting test without a capture and verify it fails.

- [ ] T004 [US1] Audit and annotate affected tests identified in `specs/detection-draft.json`.
- [ ] T005 [P] [US1] Keep intentional deprecation assertions explicit in `tests/test_utils_deprecate.py`.
- [ ] T006 [P] [US1] Keep warning expectations explicit in `tests/test_scrapy__getattr__.py`.
- [ ] T007 [P] [US1] Review warning filters in `tests/test_downloadermiddleware_httpcompression.py`.
- [ ] T008 [US1] Resolve any unhandled warnings in report-based or asynchronous test paths without weakening assertions.

## Phase 4: Polish

- [ ] T009 Validate representative dependency combinations through the tox matrix.
- [ ] T010 Document any new exception with its warning class, scope, and reason.

## Dependencies & Execution Order

Setup precedes foundational configuration. The global policy precedes auditing.
Independent test modules can be audited in parallel after T003.

## Implementation Strategy

Enable the policy first, then fix only failures exposed by the affected test
modules before expanding validation to the full tox matrix.
