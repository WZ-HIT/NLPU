# Feature Specification: Bootstrap Error Exit Codes

**Feature Branch**: `001-bootstrap-error-exit-codes`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Return exit code 1 from `check`, `parse`, and `fetch` on bootstrap errors.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Detect failed command startup (Priority: P1)

As a command-line user or automation script, I need `scrapy check`, `scrapy parse`, and
`scrapy fetch` to report a failed startup through exit code `1`, so that failures are not
silently treated as successful runs.

**Why this priority**: Exit status is the primary machine-readable result for scripts and
CI systems; an incorrect zero status hides a failed command.

**Independent Test**: Start each command in a project where crawler bootstrap fails and
assert that the process exits with status `1`.

**Acceptance Scenarios**:

1. **Given** a project whose crawler bootstrap fails, **When** `scrapy check` runs,
   **Then** the process exits with status `1`.
2. **Given** a project whose crawler bootstrap fails, **When** `scrapy parse <url>` runs,
   **Then** the process exits with status `1`.
3. **Given** a project whose crawler bootstrap fails, **When** `scrapy fetch <url>` runs,
   **Then** the process exits with status `1`.

### User Story 2 - Preserve successful behavior (Priority: P2)

As an existing user, I need successful `check`, `parse`, and `fetch` runs to continue
exiting with status `0`.

**Why this priority**: The new failure signal must not change established successful
command behavior.

**Independent Test**: Run each affected command through its normal successful path and
assert that the process exits with status `0`.

**Acceptance Scenarios**:

1. **Given** a valid project and command input, **When** any affected command completes
   successfully, **Then** the process exits with status `0`.

### Edge Cases

- Bootstrap fails after the crawler process has started.
- Bootstrap fails without producing a usable spider or response.
- An argument-validation failure must retain its existing usage exit code `2`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `scrapy check` MUST exit with status `1` when crawler bootstrap fails.
- **FR-002**: `scrapy parse` MUST exit with status `1` when crawler bootstrap fails.
- **FR-003**: `scrapy fetch` MUST exit with status `1` when crawler bootstrap fails.
- **FR-004**: Successful runs of all three commands MUST continue to exit with status `0`.
- **FR-005**: Existing usage-error behavior, including exit status `2`, MUST remain
  unchanged.

### Key Entities

- **Command result**: The process exit status produced after a command finishes.
- **Bootstrap failure**: A startup failure recorded by the crawler process that prevents
  the command from acquiring a usable crawler or spider.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All three affected commands return status `1` in bootstrap-failure
  scenarios.
- **SC-002**: Successful paths for the affected commands continue to return status `0`.
- **SC-003**: Existing argument-validation paths continue to return status `2`.

## Assumptions

- Bootstrap state is already tracked by the crawler process, as used by `crawl` and
  `runspider`.
- Exit status `1` is the established application-failure convention in this project.
- No new user-facing option or configuration is required.
