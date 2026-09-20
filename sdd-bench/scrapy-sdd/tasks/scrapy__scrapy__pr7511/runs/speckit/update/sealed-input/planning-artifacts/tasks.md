# Tasks: Python 3.15 CI Compatibility

**Input**: Design documents from `specs/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`

**Tests**: Test tasks are included because the PR identifies `scrapy.utils.misc.walk_modules_iter` as compatibility-sensitive. The planning-only execution does not run these tasks.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the exact CI and compatibility surfaces.

- [ ] T001 Review the current interpreter matrix in `.github/workflows/tests-ubuntu.yml`, `.github/workflows/tests-vcs-deps.yml`, `.github/workflows/tests-windows.yml`, and `.github/workflows/tests-macos.yml`
- [ ] T002 Review Python-version constraints and classifiers in `pyproject.toml` and tox interpreter settings in `tox.ini`
- [ ] T003 [P] Record the direct and indirect test candidates for `walk_modules_iter` in `specs/detection-draft.json`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Resolve the compatibility contract before implementation.

**Critical**: Complete this phase before changing CI or production behavior.

- [ ] T004 Document the Python 3.15 prerequisite interpreter behavior and dependency limitations in `specs/research.md`
- [ ] T005 Document the module discovery contract and failure semantics in `specs/data-model.md`
- [ ] T006 Confirm that existing Python 3.10 through 3.14 matrix entries must remain unchanged unless a documented dependency constraint requires an update

**Checkpoint**: CI targets, compatibility contract, and dependency constraints are understood.

---

## Phase 3: User Story 1 - Validate Scrapy on Python 3.15 (Priority: P1) 🎯 MVP

**Goal**: Add an executable Python 3.15 CI configuration on the supported runner.

**Independent Test**: Run the designated Python 3.15 job and verify that interpreter setup, dependency installation, and the selected test environment complete.

### Implementation for User Story 1

- [ ] T007 [US1] Add a Python 3.15 entry to the supported Linux matrix in `.github/workflows/tests-ubuntu.yml`
- [ ] T008 [US1] Enable prerelease interpreter selection for the Python 3.15 setup path in `.github/workflows/tests-ubuntu.yml`
- [ ] T009 [P] [US1] Confirm or update the constrained Python 3.15 CI entry in `.github/workflows/tests-vcs-deps.yml`
- [ ] T010 [US1] Add an explicit dependency-based exclusion or omission comment for unsupported platform entries in `.github/workflows/tests-windows.yml` and `.github/workflows/tests-macos.yml`
- [ ] T011 [US1] Update Python support metadata in `pyproject.toml` only if the project is claiming official Python 3.15 support
- [ ] T012 [US1] Verify the Python 3.15 job is not skipped and produces a normal pass or fail result

**Checkpoint**: Python 3.15 executes in CI on the supported platform.

---

## Phase 4: User Story 2 - Preserve Module Discovery Behavior (Priority: P1)

**Goal**: Keep `walk_modules_iter` behavior compatible across Python 3.10 through 3.15.

**Independent Test**: Run the direct module-walker tests plus command and spider discovery consumer tests under the affected interpreters.

### Tests for User Story 2

- [ ] T013 [P] [US2] Confirm direct coverage for package, nested package, single module, missing module, deprecation, and egg cases in `tests/test_utils_misc/__init__.py`
- [ ] T014 [P] [US2] Confirm consumer coverage for module discovery and error handling in `tests/test_spiderloader/__init__.py`
- [ ] T015 [P] [US2] Confirm command-discovery coverage for built-in and project command modules in `tests/test_commands.py`

### Implementation for User Story 2

- [ ] T016 [US2] Reproduce the Python 3.15 module-discovery incompatibility with the direct tests in `tests/test_utils_misc/__init__.py`
- [ ] T017 [US2] Make the minimal compatibility change in `scrapy/utils/misc.py` while preserving deferred import errors and recursive discovery
- [ ] T018 [US2] Update version-sensitive expectations in `tests/test_utils_misc/__init__.py` only where behavior intentionally differs
- [ ] T019 [US2] Run direct module-walker validation as described in `specs/quickstart.md`
- [ ] T020 [US2] Run command and spider discovery validation as described in `specs/quickstart.md`
- [ ] T021 [US2] Confirm Python 3.10 through 3.14 compatibility by running the direct tests across the supported local environments

**Checkpoint**: Module discovery passes directly and through both production consumers.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final consistency and release-note work.

- [ ] T022 [P] Update user-facing release notes or documentation if Python 3.15 support status changes
- [ ] T023 Review `.github/workflows/checks.yml` and `pyproject.toml` for interpreter-version assumptions that would become stale
- [ ] T024 Run the full selected CI environment and review all matrix jobs
- [ ] T025 Verify `specs/detection-draft.json` remains limited to repository-relative test paths and contains no project-code candidates

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on setup review.
- **User Story 1 (Phase 3)**: Depends on foundational completion.
- **User Story 2 (Phase 4)**: Depends on foundational completion.
- **Polish (Phase 5)**: Depends on both user stories.

### User Story Dependencies

- **User Story 1 (P1)**: Can proceed independently of the production fix once CI prerequisites are known.
- **User Story 2 (P1)**: Can proceed independently of the CI changes once the compatibility contract is known.

### Within Each User Story

- Confirm test coverage before changing production behavior.
- Make the smallest production compatibility change.
- Run direct tests before consumer tests.
- Treat the full CI run as the final integration gate.

### Parallel Opportunities

- Setup reviews T001 and T002 can run in parallel.
- Test-coverage confirmation tasks T013, T014, and T015 can run in parallel.
- CI metadata review T022 and stale-version review T023 can run in parallel.

---

## Implementation Strategy

### MVP First

1. Complete setup and foundational review.
2. Add a working Python 3.15 CI entry.
3. Confirm direct module-walker coverage and reproduce the compatibility issue.
4. Make the minimal production change.
5. Validate direct tests, consumer tests, then the full CI matrix.

### Incremental Delivery

1. Python 3.15 job passes on the constrained supported environment.
2. Module-walker compatibility is fixed and covered directly.
3. Command and spider discovery consumers pass.
4. Platform exclusions and support metadata are documented.

## Notes

- This planning execution does not run tests and does not modify project code or test files.
- Candidate test paths in `specs/detection-draft.json` are repository-relative.
