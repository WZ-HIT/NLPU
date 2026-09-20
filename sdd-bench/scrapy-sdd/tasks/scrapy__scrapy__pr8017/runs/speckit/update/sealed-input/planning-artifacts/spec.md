# Feature Specification: Type the Remaining Exempt Test Modules

**Feature Branch**: `8017-type-last-untyped-test-modules`

**Created**: 2026-09-19

**Status**: Planned

**Input**: Scrapy PR #8017, "Type the last tests.* modules under check_untyped_defs = false"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Enforce body checking for every exempt test module (Priority: P1)

As a Scrapy maintainer, I want the remaining test modules to pass mypy with `check_untyped_defs` enabled so that test bodies receive the same static checking as type-annotated test code.

**Why this priority**: This completes the incremental typing effort and removes the final broad exception in `pyproject.toml`.

**Independent Test**: Remove the 14 exempt module entries, run `mypy scrapy tests`, and confirm that no errors originate from the listed test modules.

**Acceptance Scenarios**:

1. **Given** the current mypy exemption list, **When** the listed modules are annotated and their exemption entries are removed, **Then** mypy checks function bodies in those modules under strict settings.
2. **Given** annotations that preserve runtime behavior, **When** the affected tests run, **Then** their results match the pre-change baseline.

---

### User Story 2 - Keep test behavior unchanged (Priority: P2)

As a Scrapy contributor, I want the typing work to avoid behavioral changes so that existing tests remain reliable.

**Why this priority**: Annotation-only changes should not alter fixtures, assertions, queue behavior, signal handling, or test outcomes.

**Independent Test**: Compare the affected test suite before and after the typing changes and confirm equivalent results.

**Acceptance Scenarios**:

1. **Given** a typed helper or fixture, **When** its test module is collected and executed, **Then** the same test cases are collected and pass.
2. **Given** a type-only edit such as `Any`, `cast`, or a narrowing assertion, **When** tests execute, **Then** no runtime branch or fixture contract changes.

---

### User Story 3 - Preserve an auditable migration (Priority: P3)

As a reviewer, I want each removed mypy exception to correspond to a typed test module so that the migration is easy to review and revert.

**Why this priority**: A one-module-at-a-time mapping keeps the change reviewable and prevents accidentally enabling checking for unrelated modules.

**Independent Test**: Review the diff and verify that each removed module entry maps to a changed test file and that no unrelated mypy overrides changed.

**Acceptance Scenarios**:

1. **Given** the final mypy configuration, **When** the exempt-module block is removed, **Then** no `tests.*` module remains configured with `check_untyped_defs = false`.

### Edge Cases

- Dynamically typed mocks, Twisted deferreds, and third-party queue classes may require explicit `Any` or `cast` rather than overly narrow annotations.
- Delegating test subclasses may inherit methods whose return types are declared in a base or third-party class.
- Package-level test modules (`tests/test_cmdline` and `tests/test_settings`) include fixtures and helper functions as well as collected tests.
- Type annotations must remain compatible with the project's Python 3.10 minimum.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All test code governed by the 14 module entries in the current `check_untyped_defs = false` override MUST be annotated or narrowed sufficiently for strict mypy checking.
- **FR-002**: The mypy override MUST stop disabling `check_untyped_defs` for those test modules once they are clean.
- **FR-003**: The change MUST preserve the set of collected tests and their runtime behavior.
- **FR-004**: Type annotations MUST use constructs supported by Python 3.10.
- **FR-005**: The typed code MUST remain compatible with the project's existing mypy strict settings and dependency stubs.
- **FR-006**: The change MUST remain limited to test typing and the corresponding mypy configuration; production behavior MUST not change.

### Key Entities

- **Exempt test module**: A module listed in the `[[tool.mypy.overrides]]` block that currently sets `check_untyped_defs = false`.
- **Candidate test file**: A repository-relative test file that carries collectible tests for one of those modules.
- **Typing constraint**: An annotation, cast, guard, or protocol adjustment needed to satisfy strict mypy without changing runtime behavior.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The mypy exemption block contains zero remaining test modules with `check_untyped_defs = false`.
- **SC-002**: `mypy scrapy tests` completes with zero errors under the repository's pinned mypy environment.
- **SC-003**: All 14 candidate test modules collect the same test identifiers as before the typing change.
- **SC-004**: The affected test suite has no new failures compared with the base commit.

## Assumptions

- The mypy configuration at the base commit is authoritative for identifying the remaining exemption scope.
- The change is annotation-only and does not intentionally alter test semantics.
- Existing dependency stubs and pinned mypy versions are used for validation.
- The mounted planning directory is `/workspace/specs`; project code and tests remain read-only during planning.
