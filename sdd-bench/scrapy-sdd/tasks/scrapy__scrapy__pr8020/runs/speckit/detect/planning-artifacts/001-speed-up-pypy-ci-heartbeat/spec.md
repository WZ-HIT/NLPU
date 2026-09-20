# Feature Specification: Speed up PyPy CI and heartbeat waits

**Feature Branch**: `001-speed-up-pypy-ci-heartbeat`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Scrapy pull request 8020: speed up the PyPy CI job and tests that wait on the engine heartbeat.

## User Scenarios & Testing

### User Story 1 - Reduce PyPy subprocess coverage overhead (Priority: P1)

As a Scrapy maintainer, I want the PyPy CI job to avoid unnecessary subprocess coverage measurement so that the job completes substantially faster without reducing useful Codecov signal.

**Why this priority**: This is the main source of the reported CI slowdown.

**Independent Test**: Run the PyPy extra-dependencies job configuration and confirm subprocesses are not coverage-instrumented while the parent test process still produces the intended coverage report.

**Acceptance Scenarios**:

1. **Given** the PyPy extra-dependencies CI environment, **when** coverage is enabled, **then** subprocess coverage is disabled.
2. **Given** the change, **when** coverage is uploaded, **then** PyPy-specific coverage remains represented by the parent process.

---

### User Story 2 - Remove heartbeat-related test delays (Priority: P2)

As a Scrapy developer, I want tests that depend on the engine heartbeat to use a shorter interval or avoid waiting for the production interval so that the suite runs faster.

**Why this priority**: These waits add avoidable latency to local and CI test runs.

**Independent Test**: Run the affected engine-loop tests and verify their timing assumptions still pass with the reduced heartbeat interval.

**Acceptance Scenarios**:

1. **Given** a test that waits for the engine to process scheduled work, **when** the test uses the shortened heartbeat interval, **then** the test completes without changing production behavior.

### Edge Cases

- Coverage must remain active for the main PyPy test process unless explicitly intended otherwise.
- Shortened heartbeat timing must not make ordering or shutdown assertions flaky.
- Non-PyPy coverage behavior must remain unchanged.

## Requirements

### Functional Requirements

- **FR-001**: The PyPy extra-dependencies CI job MUST disable coverage measurement in subprocesses.
- **FR-002**: The change MUST preserve the intended Codecov coverage signal from the main PyPy process.
- **FR-003**: Tests that wait on heartbeat-driven engine processing MUST avoid unnecessary waits for the production heartbeat interval.
- **FR-004**: Production engine heartbeat behavior MUST remain unchanged.
- **FR-005**: Non-PyPy CI and coverage behavior MUST remain unchanged.

### Key Entities

- **PyPy CI job**: The Ubuntu matrix entry running `pypy3-extra-deps`.
- **Engine heartbeat**: The periodic engine call that keeps scheduled work moving.
- **Candidate tests**: Tests exercising subprocess startup, engine lifecycle, and heartbeat-driven scheduling.

## Success Criteria

### Measurable Outcomes

- **SC-001**: The PyPy extra-dependencies job no longer measures coverage in child processes.
- **SC-002**: Heartbeat-dependent tests complete without waiting for the full production heartbeat interval.
- **SC-003**: Existing assertions for request ordering, lifecycle, and shutdown continue to pass.

## Assumptions

- Codecov receives sufficient coverage from the CPython jobs and the PyPy parent process.
- The heartbeat interval remains a production constant; only tests may override it.
- The PR may adjust test timeouts that were sized for subprocess coverage overhead.
