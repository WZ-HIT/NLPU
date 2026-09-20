---
description: "Task list for typing the remaining mypy-exempt test modules"
---

# Tasks: Type the Remaining Exempt Test Modules

**Input**: Design documents from `/workspace/specs/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `quickstart.md`

**Tests**: Test execution is included only as verification of behavior preservation; the feature does not add new test behavior.

## Phase 1: Setup

- [ ] T001 Record the current exempt module list and candidate mapping from `pyproject.toml` and `data-model.md`
- [ ] T002 Establish a baseline test collection result for the 14 candidate test files without changing project code or tests
- [ ] T003 Confirm the pinned mypy and Python 3.10 compatibility constraints in `tox.ini`

---

## Phase 2: Foundational

- [ ] T004 Run `mypy scrapy tests` before annotation work and save the errors attributable to the 14 exempt modules
- [ ] T005 Group typing fixes by candidate file so each module can be checked and reviewed independently
- [ ] T006 Define a local policy for `Any`, `cast`, protocols, and narrowly scoped ignores at third-party or mock boundaries

---

## Phase 3: User Story 1 - Enforce body checking (Priority: P1)

**Goal**: Make every formerly exempt test module clean under strict mypy body checking.

**Independent Test**: Remove all 14 module entries from the exemption block and run `mypy scrapy tests`.

- [ ] T007 [US1] Type helpers and tests in `tests/test_cmdline/__init__.py`
- [ ] T008 [P] [US1] Type spider methods and tests in `tests/test_downloaderslotssettings.py`
- [ ] T009 [P] [US1] Type helpers, duplicate-filter subclasses, and tests in `tests/test_dupefilters.py`
- [ ] T010 [P] [US1] Type fixtures and tests in `tests/test_extension_statsmailer.py`
- [ ] T011 [P] [US1] Type helpers and tests in `tests/test_extension_throttle.py`
- [ ] T012 [P] [US1] Type extractor test classes and local callbacks in `tests/test_linkextractors.py`
- [ ] T013 [P] [US1] Type formatter helpers, subclasses, and tests in `tests/test_logformatter.py`
- [ ] T014 [P] [US1] Type mail sender test helpers and tests in `tests/test_mail.py`
- [ ] T015 [P] [US1] Type priority queue helpers and tests in `tests/test_pqueues.py`
- [ ] T016 [P] [US1] Type scheduler implementations, mixins, and tests in `tests/test_scheduler_base.py`
- [ ] T017 [P] [US1] Type fixtures, helpers, components, and tests in `tests/test_settings/__init__.py`
- [ ] T018 [P] [US1] Type queue helpers and test classes in `tests/test_squeues.py`
- [ ] T019 [P] [US1] Type request queue fixtures and test classes in `tests/test_squeues_request.py`
- [ ] T020 [P] [US1] Type fixtures, mocks, and tests in `tests/test_stats.py`
- [ ] T021 [US1] Remove the completed `tests.*` module list and `check_untyped_defs = false` override from `pyproject.toml`
- [ ] T022 [US1] Run `mypy scrapy tests` and resolve any errors in the candidate files

**Checkpoint**: No test module remains exempt from body checking, and mypy is clean.

---

## Phase 4: User Story 2 - Preserve behavior (Priority: P2)

**Goal**: Confirm annotation-only changes do not alter test outcomes.

**Independent Test**: Run the focused test suite and compare it with the baseline.

- [ ] T023 [US2] Run the focused suite from `quickstart.md`
- [ ] T024 [US2] Compare collected test identifiers with the recorded baseline
- [ ] T025 [US2] Inspect annotations involving mocks, callbacks, Twisted deferreds, and third-party queues for runtime-affecting changes

**Checkpoint**: The candidate suite behaves as before the typing changes.

---

## Phase 5: User Story 3 - Preserve an auditable migration (Priority: P3)

**Goal**: Make the mapping between removed exceptions and typed files reviewable.

**Independent Test**: Review the diff against `data-model.md` and the detection draft.

- [ ] T026 [US3] Verify each removed override entry maps to exactly one typed candidate test file
- [ ] T027 [US3] Verify no production source file or unrelated mypy override changed
- [ ] T028 [US3] Record commands, outcomes, and any justified local ignores in the pull request description

**Checkpoint**: The migration is complete and reviewable.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T029 Run the repository pre-commit checks for changed files
- [ ] T030 Confirm the final diff has no behavioral test edits and no unrelated formatting churn
- [ ] T031 Re-run `mypy scrapy tests` and the focused tests on the final revision

---

## Dependencies & Execution Order

- Setup and Foundational tasks block all story work.
- US1 is the critical path; US2 and US3 validate the result.
- Tasks T008-T020 can run in parallel by file.
- T021 must follow completion of T007-T020.
- T022 must follow T021.

## Implementation Strategy

Complete the foundational baseline, type files in parallel batches, enable strict body checking by removing the override, then validate behavior and audit the final diff.
