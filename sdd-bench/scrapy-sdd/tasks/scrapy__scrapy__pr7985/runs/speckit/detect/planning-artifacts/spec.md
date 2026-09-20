# Feature Specification: Rerun Internet-Dependent Test Failures

**Created**: 2026-09-20

**Status**: Draft

**Input**: `scrapy/scrapy` pull request 7985

## User Scenarios & Testing

### User Story 1 - Tolerate transient Internet failures (Priority: P1)

As a maintainer, I want tests marked `requires_internet` to be attempted again after failure so transient DNS, TLS, or remote-server failures do not make CI red.

**Independent Test**: Force an initial failure in a marked test and verify that it is retried while a permanent failure still fails.

**Acceptance Scenarios**:

1. **Given** a marked test that passes on retry, **When** it runs, **Then** the retry can make it pass.
2. **Given** a marked test that always fails, **When** retries are exhausted, **Then** the test remains failed.

### Edge Cases

- Tests without `requires_internet` must not be retried by this feature.
- Retries must not hide deterministic regressions.

## Requirements

### Functional Requirements

- **FR-001**: Internet-dependent tests MUST be identified by `requires_internet`.
- **FR-002**: A marked test that fails MUST be retried at least once.
- **FR-003**: A marked test MUST fail after retries are exhausted.
- **FR-004**: Non-marked tests MUST NOT be retried by this feature.

## Success Criteria

- **SC-001**: Every marked test receives an additional attempt after an initial failure.
- **SC-002**: A permanently failing marked test still produces a failing suite.
- **SC-003**: Tests without the marker retain their existing attempt count.

## Assumptions

- External-service transience is the intended source of flakiness.
- The existing `requires_internet` marker remains canonical.
- Retry configuration does not alter production Scrapy behavior.
