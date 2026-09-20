# Feature Specification: CI Warnings as Errors

**Feature Branch**: `001-ci-warnings-as-errors`

**Created**: 2026-09-20

**Status**: Draft

**Input**: PR 7702: CI warnings -> errors (fixes #7262)

## User Scenarios & Testing

### User Story 1 - Fail on unexpected warnings (Priority: P1)

As a Scrapy maintainer, I want CI test runs to fail when code emits an
unexpected warning so warning regressions are caught before release.

**Why this priority**: This is the complete purpose of the change.

**Independent Test**: Configure the test runner to treat warnings as errors,
then run a test that emits an unexpected warning and confirm collection or
execution fails.

**Acceptance Scenarios**:

1. **Given** the pytest configuration, **When** an unhandled warning is
   emitted, **Then** the test fails.
2. **Given** a test intentionally asserting a warning, **When** it uses the
   established warning-capture mechanism, **Then** it still passes.
3. **Given** a known third-party or intentional warning, **When** an explicit
   narrowly scoped exception exists, **Then** the test suite can proceed.

### Edge Cases

- Warnings emitted during collection or setup.
- Warning classes and messages that differ across supported dependencies.
- Subprocess tests, where pytest warning filters are not inherited.
- Tests that intentionally trigger deprecations and assert them.

## Requirements

### Functional Requirements

- **FR-001**: The standard pytest configuration MUST treat warnings as errors.
- **FR-002**: Intentional warning-producing tests MUST continue to assert the
  warning without becoming failures.
- **FR-003**: Every warning exception MUST be narrow in class, message, or
  module scope and MUST include a reason where the warning is expected.
- **FR-004**: Warning-to-error behavior MUST apply globally rather than only to
  selected "latest" dependency environments.
- **FR-005**: Changes MUST not weaken existing test coverage.

### Key Entities

- **Warning policy**: Pytest's global filter list.
- **Warning exception**: A scoped ignore or capture rule for an intentional or
  external warning.
- **Affected test**: A test that emits, captures, or suppresses warnings.

## Success Criteria

- **SC-001**: An unexpected warning causes the corresponding test to fail.
- **SC-002**: The existing suite passes in every supported test environment
  after intentional warnings are handled.
- **SC-003**: No warning exception is broader than the behavior it documents.

## Assumptions

- Existing uses of `pytest.warns`, `pytest.mark.filterwarnings`, and
  `warnings.catch_warnings` are the intended mechanisms for expected warnings.
- Dependency-specific warnings already suppressed for external reasons remain
  valid when narrowly scoped.
- This change affects test and CI configuration, not runtime behavior for
  Scrapy users.
