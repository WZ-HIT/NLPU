# Feature Specification: Re-enable DirtyReactorAggregateError Tests

**Feature Branch**: `001-reenable-dirty-reactor-tests`

**Created**: 2026-09-17

**Status**: Draft

**Input**: Pull request 8073 for `scrapy/scrapy`, based on commit
`11079cb1c85b9e75a39a7269943c69d1a975d485`: "Re-enable tests with
DirtyReactorAggregateError comments."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Restore Full Test Coverage (Priority: P1)

As a Scrapy maintainer, I want tests that were skipped because of historical
`DirtyReactorAggregateError` behavior to run again so that regressions in the
affected downloader paths are detected.

**Why this priority**: The skips hide coverage on supported runtime
combinations. Restoring them is the entire purpose of the pull request.

**Independent Test**: Inspect the affected test definitions and confirm that
the platform/event-loop skip branch is removed; then collect the associated
tests without running the suite.

**Acceptance Scenarios**:

1. **Given** a supported Windows asyncio test environment, **When** the affected
   downloader tests are collected, **Then** they are no longer excluded by a
   `DirtyReactorAggregateError` skip.
2. **Given** the repository at the pull request base, **When** the affected test
   symbols are located, **Then** each one is present in a repository-relative
   test file.
3. **Given** the change is evaluated, **When** the affected files are compared,
   **Then** no unrelated downloader behavior is required to change.

### Edge Cases

- The three existing occurrences may be in two different test files.
- One occurrence is an FTP credential test; two are inherited HTTP timeout
  tests in a shared base class.
- A skip may remain necessary if the underlying Twisted behavior still applies;
  detection must identify the affected symbols even when that outcome is later
  decided by maintainers.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Detection MUST enumerate every repository-relative test file
  containing the three `DirtyReactorAggregateError` skip comments at the base
  commit.
- **FR-002**: Detection MUST identify the test symbols associated with those
  comments, including inherited HTTP timeout tests.
- **FR-003**: The detection draft MUST contain only a `candidates` array, and
  each entry MUST provide `path`, `symbols`, and `reason`.
- **FR-004**: Planning artifacts MUST be written only under the mounted
  `/workspace/specs` planning directory.
- **FR-005**: No project code or test file may be modified, and no tests may be
  executed during this planning/detection stage.

### Key Entities

- **Candidate test file**: A repository-relative path under `tests/` containing
  one or more affected test symbols.
- **Test symbol**: The qualified pytest function or method whose skip condition
  is under review.
- **Detection draft**: The machine-readable candidates document used by the
  later update stage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of files containing `DirtyReactorAggregateError` in
  `tests/` are represented in `detection-draft.json`.
- **SC-002**: Every listed candidate includes at least one valid qualified test
  symbol and a specific reason tied to removal or review of the skip.
- **SC-003**: Exactly one `detection-draft.json` is created in the planning
  directory.
- **SC-004**: No source, test, or unrelated repository file is changed.

## Assumptions

- The pull request is a test-maintenance change and does not intentionally add
  product behavior.
- Repository-relative paths are relative to `/workspace`.
- The affected shared HTTP base methods are validated through concrete
  subclasses, but the candidate file is the file changed in the pull request.
