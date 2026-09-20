# Tasks: Speed up PyPy CI and heartbeat waits

**Input**: Design documents from `specs/001-speed-up-pypy-ci-heartbeat/`

**Prerequisites**: plan.md, spec.md

## Phase 1: Setup

- [ ] T001 Confirm the PyPy matrix entry and coverage configuration in `.github/workflows/tests-ubuntu.yml`, `tox.ini`, and `pyproject.toml`.
- [ ] T002 [P] Confirm heartbeat-related timing assumptions in `tests/test_engine.py`, `tests/test_engine_close_spider.py`, and `tests/test_engine_loop.py`.

## Phase 2: Foundational

- [ ] T003 Document the selected subprocess-coverage disablement mechanism and its PyPy-only scope in `specs/001-speed-up-pypy-ci-heartbeat/research.md`.
- [ ] T004 Identify the smallest test-only heartbeat interval override and affected timing-sensitive tests in `specs/001-speed-up-pypy-ci-heartbeat/research.md`.

## Phase 3: User Story 1 - PyPy subprocess coverage

**Goal**: Make the PyPy extra-dependencies CI job avoid subprocess coverage overhead.

**Independent Test**: Inspect the selected PyPy job environment and confirm child processes do not start with coverage instrumentation while the parent job retains its intended report.

- [ ] T005 [US1] Update the PyPy extra-dependencies coverage setting in `.github/workflows/tests-ubuntu.yml`.
- [ ] T006 [P] [US1] Update the corresponding PyPy tox command or coverage configuration in `tox.ini` or `pyproject.toml` if the CI setting alone cannot disable subprocess measurement.
- [ ] T007 [US1] Verify the other coverage-enabled matrix entries remain unchanged.

## Phase 4: User Story 2 - Heartbeat test latency

**Goal**: Remove avoidable waits for the five-second production heartbeat in tests.

- [ ] T008 [P] [US2] Add or adjust a test-scoped heartbeat interval override in `tests/test_engine_loop.py`.
- [ ] T009 [P] [US2] Adjust engine lifecycle timing assertions in `tests/test_engine.py` if they wait on heartbeat-driven processing.
- [ ] T010 [P] [US2] Adjust heartbeat teardown coverage in `tests/test_engine_close_spider.py` if the override changes its assumptions.
- [ ] T011 [US2] Confirm production heartbeat behavior in `scrapy/core/engine.py` is unchanged.

## Phase 5: Polish

- [ ] T012 [P] Review subprocess timeout/comment assumptions in `tests/test_command_shell.py`.
- [ ] T013 [P] Review subprocess timeout/comment assumptions in `tests/test_crawler_subprocess.py`.
- [ ] T014 Confirm all detection candidates are present in `specs/001-speed-up-pypy-ci-heartbeat/detection-draft.json`.

## Dependencies & Execution Order

- Phase 1 has no dependencies.
- Phase 2 depends on Phase 1.
- User Story 1 and User Story 2 can proceed independently after Phase 2.
- Polish depends on both user stories.

## Implementation Strategy

Implement the PyPy CI change first because it directly addresses the largest slowdown. Then shorten heartbeat-dependent waits with test-scoped overrides, keeping production timing and all unrelated coverage jobs unchanged.
