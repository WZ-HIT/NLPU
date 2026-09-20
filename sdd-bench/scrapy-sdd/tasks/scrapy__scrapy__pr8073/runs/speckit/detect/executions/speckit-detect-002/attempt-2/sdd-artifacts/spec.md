# Feature Specification: Re-enable DirtyReactorAggregateError Tests

**Feature Branch**: `re-enable-dirty-reactor-tests`

**Created**: 2026-09-19

**Status**: Draft

**Input**: Pull request `scrapy/scrapy#8073`, "Re-enable tests with DirtyReactorAggregateError comments."

## User Scenarios & Testing

### User Story 1 - Restore Cross-Platform Coverage (Priority: P1)

As a Scrapy maintainer, I want tests that were skipped for Windows asyncio dirty-reactor
failures to run again, so that regressions in HTTP and FTP download handling are detected
on every supported test configuration.

**Why this priority**: The skipped paths cover timeout and connection-failure behavior
that otherwise has a coverage gap on Windows with the asyncio reactor.

**Independent Test**: Run the previously skipped tests on Windows with the asyncio
reactor and confirm they execute instead of reporting a skip.

**Acceptance Scenarios**:

1. **Given** the Windows asyncio test configuration, **when** the FTP invalid-credentials
   test runs, **then** it asserts the expected connection failure without being skipped.
2. **Given** the Windows asyncio test configuration, **when** the HTTP timeout tests run,
   **then** each asserts the expected timeout without being skipped.

## Requirements

### Functional Requirements

- **FR-001**: The FTP invalid-credentials test MUST no longer skip on Windows with the
  asyncio reactor.
- **FR-002**: The HTTP no-data timeout test MUST no longer skip on Windows with the asyncio
  reactor.
- **FR-003**: The HTTP hanging-response timeout test MUST no longer skip on Windows with the
  asyncio reactor.
- **FR-004**: The re-enabled tests MUST preserve their existing behavioral assertions.
- **FR-005**: The change MUST remain limited to the affected test definitions unless an
  unrelated failure requires separate justification.

### Key Entities

- **Dirty-reactor skip condition**: The Windows-asyncio condition and explanatory comment
  that currently prevents a test from running.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All three affected tests execute rather than skip in the Windows asyncio test
  configuration.
- **SC-002**: The targeted tests pass in their restored form.
- **SC-003**: No unrelated test file is changed by the implementation.

## Assumptions

- The referenced Twisted dirty-reactor issue has been resolved or no longer affects these
  tests in the supported dependency set.
- Existing test assertions already describe the intended behavior and do not need changes.
- Validation is performed by Scrapy's normal pytest and pytest-twisted matrix.
