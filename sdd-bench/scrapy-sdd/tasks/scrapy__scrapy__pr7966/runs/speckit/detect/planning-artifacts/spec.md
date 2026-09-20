# Feature Specification: Address VCS workflow warnings

**Created**: 2026-09-20

**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Keep the VCS dependency run actionable (Priority: P1)

Maintainers who rely on the scheduled VCS dependency workflow need its test output to stay readable: warnings coming from development branches of third-party dependencies must not drown out warnings that point at Scrapy itself.

**Independent Test**: Run the `vcs-deps` tox environment (implementation phase only) and confirm the run completes with warnings that are either resolved, narrowly scoped to a known dependency limitation, or still attributable to Scrapy.

**Acceptance Scenarios**:

1. Given development revisions of the dependencies the workflow installs, when the workflow runs, then every remaining warning is actionable and has an identified origin.
2. Given a warning that originates outside Scrapy, when it cannot be fixed in Scrapy, then the handling is narrow enough that Scrapy-origin warnings still surface.

### Edge Cases

- A development dependency changes an API before its next release.
- A warning appears only with optional components (pyOpenSSL, cryptography, Twisted, httpx2, h2, brotli/zstandard, uvloop).
- Warning text or emitting module changes between dependency revisions, invalidating a message-based filter.

## Requirements

### Functional Requirements

- **FR-001**: The VCS workflow MUST keep installing dependencies from their development branches.
- **FR-002**: Scrapy-origin warnings MUST be addressed rather than globally suppressed.
- **FR-003**: Dependency-origin warnings that cannot be fixed in Scrapy MUST be filtered narrowly (by message/category) and documented.
- **FR-004**: Warning-sensitive tests MUST keep asserting the intended behavior after any filter change.

### Key Entities

- **VCS dependency environment**: the `vcs-deps` tox environment and its workflow invocation.
- **Warning**: a diagnostic emitted while installing, collecting, or running tests.
- **Test candidate**: an existing repository-relative test path likely to validate warning handling.

## Success Criteria

- **SC-001**: The VCS dependency workflow completes with no unexplained warning noise.
- **SC-002**: All candidate warning-sensitive tests pass.
- **SC-003**: No warning category is suppressed repository-wide.

## Assumptions

- The change is limited to warning handling and CI/test configuration; runtime behavior for users is unchanged.
- Existing narrow filters in the test suite are the accepted pattern for dependency-origin warnings.
