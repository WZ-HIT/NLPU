# Feature Specification: Open-in-Browser ReDoS Test Stability

**Feature Branch**: `open-in-browser-redos-test-stability`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Pull request task for `scrapy/scrapy` PR 7995: "Stop the open_in_browser ReDoS tests from failing on slow interpreters"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reliable ReDoS Regression Checks (Priority: P1)

As a Scrapy maintainer, I want the open-in-browser ReDoS regression checks to pass on slow interpreters so that a slow or heavily loaded CI worker does not create a false failure while the checks continue to detect catastrophic processing.

**Why this priority**: The change is narrowly concerned with removing interpreter-speed flakiness from two existing regression checks. It delivers value only if both stable CI behavior and meaningful ReDoS protection are preserved.

**Independent Test**: Exercise the two affected checks on a deliberately slow interpreter or constrained CPU allocation and confirm that normal linear processing passes. Exercise the same checks against a vulnerable implementation and confirm that catastrophic backtracking still produces a failure.

**Acceptance Scenarios**:

1. **Given** a slow interpreter, **when** the affected open-in-browser checks run with pathological inputs, **then** they do not fail solely because normal processing exceeds the old fixed CPU allowance.
2. **Given** a vulnerable regular-expression implementation, **when** the same pathological inputs are processed, **then** the regression checks still fail.
3. **Given** a normal interpreter, **when** the affected checks run repeatedly, **then** both checks pass without changing the user-visible behavior of `open_in_browser`.

### Edge Cases

- CI scheduling, emulation, instrumentation, or CPU contention may make a normal implementation substantially slower than it is on a developer machine.
- An excessively permissive limit could make the regression checks ineffective against catastrophic processing.
- A timing check that relies on wall-clock time may be affected by unrelated process scheduling; CPU-time measurement should remain the basis of the assertion unless a different approach gives a stronger and stable signal.
- The input sizes and vulnerable patterns must remain representative enough to reveal the original comment-removal and head-search ReDoS cases.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The open-in-browser comment-removal regression check MUST continue to protect against catastrophic processing of the documented pathological input.
- **FR-002**: The open-in-browser head-search regression check MUST continue to protect against catastrophic processing of the documented pathological input.
- **FR-003**: Both regression checks MUST pass reliably on a slow interpreter when `open_in_browser` handles the inputs in linear time.
- **FR-004**: The checks MUST retain a detectable failure condition for a vulnerable implementation; they MUST NOT be skipped, removed, or converted into unconditional expected failures.
- **FR-005**: The change MUST preserve the current user-visible behavior of `open_in_browser`.
- **FR-006**: The regression checks MUST remain individually discoverable by their existing test names.

### Key Entities

- **ReDoS regression check**: An automated test that supplies a pathological input and verifies that processing does not exhibit catastrophic runtime behavior.
- **Slow interpreter**: An execution environment whose normal CPU throughput is low enough that a formerly fixed micro-duration allowance is not a reliable indicator of algorithmic regression.
- **Pathological input**: The existing comment-oriented and head-oriented byte sequences that caused catastrophic backtracking in earlier regular-expression implementations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Both affected checks pass in at least 20 consecutive executions on a slow or constrained interpreter without a false timing failure.
- **SC-002**: Both affected checks still fail against a deliberately vulnerable implementation of their respective regular-expression operation.
- **SC-003**: The complete open-in-browser test module passes with no change to `open_in_browser` behavior on supported Python versions.
- **SC-004**: The detection phase identifies one candidate test module containing exactly the two ReDoS checks named by the PR scope.

## Assumptions

- The PR is test-only unless validation proves a production change is required.
- The existing `open_in_browser` implementation already avoids the original catastrophic regular expressions; PR 7995 addresses test fragility rather than reintroducing or fixing production behavior.
- CI interpreters can legitimately be much slower than the machine on which the original fixed CPU allowance was selected.
- The two existing test names and their pathological inputs remain the authoritative regression cases.
