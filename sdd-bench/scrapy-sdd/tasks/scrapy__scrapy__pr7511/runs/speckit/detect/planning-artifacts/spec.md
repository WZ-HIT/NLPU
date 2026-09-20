# Feature Specification: Python 3.15 CI Compatibility

**Feature Branch**: `001-python-315-ci`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "PR 7511, Add Python 3.15 to CI. The PR specifically calls out `scrapy/utils/misc.py::scrapy.utils.misc.walk_modules_iter`."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Validate Scrapy on Python 3.15 (Priority: P1)

As a Scrapy maintainer, I want a supported CI job to run the test suite under Python 3.15 so that prerelease compatibility regressions are caught before the interpreter is generally available.

**Why this priority**: The feature exists to make Python 3.15 a continuously tested interpreter. Without an executing CI job, compatibility cannot be demonstrated or maintained.

**Independent Test**: Run the designated Python 3.15 CI configuration and verify that installation, environment setup, and the selected tox environment complete successfully.

**Acceptance Scenarios**:

1. **Given** the project CI configuration, **When** the supported Python 3.15 job is started, **Then** CI requests a prerelease-capable Python 3.15 interpreter and runs the configured test environment.
2. **Given** a source change that is incompatible with Python 3.15, **When** the CI job runs, **Then** the job fails instead of silently skipping Python 3.15 coverage.
3. **Given** an interpreter or platform whose dependencies cannot yet support Python 3.15, **When** the CI matrix is reviewed, **Then** the exclusion and its reason are explicit.

---

### User Story 2 - Preserve Module Discovery Behavior (Priority: P1)

As a Scrapy user, I want module discovery to keep working under Python 3.15 so that command modules, spider modules, and their nested submodules continue to load correctly.

**Why this priority**: The PR explicitly identifies `scrapy.utils.misc.walk_modules_iter` as the compatibility-sensitive behavior. A CI-only addition is not sufficient if module discovery changes or fails on the target interpreter.

**Independent Test**: Exercise `walk_modules_iter` with regular packages, nested packages, single modules, an egg-backed module path, and a missing module, then verify the same observable behavior on supported Python versions.

**Acceptance Scenarios**:

1. **Given** a module path, **When** `walk_modules_iter` is consumed under Python 3.15, **Then** the module and all discoverable submodules are yielded.
2. **Given** a module that cannot be imported, **When** the generator is consumed, **Then** the import error is raised with the existing deferred-error behavior.
3. **Given** the module walker is used by command or spider loading, **When** discovery succeeds, **Then** existing command and spider-loader behavior is preserved.

### Edge Cases

- A package contains nested packages, ordinary modules, or both.
- A module is supplied by an egg-style path.
- The requested top-level module does not exist.
- A module raises an import-time error.
- Two modules contribute the same command or spider name.
- Python 3.15 dependencies may still be prerelease or lack platform wheels.
- CI must not weaken or remove coverage for Python 3.10 through 3.14.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: CI MUST include at least one Python 3.15 configuration on a supported Linux runner.
- **FR-002**: The Python 3.15 setup MUST permit prerelease interpreter versions.
- **FR-003**: The CI matrix MUST preserve existing supported Python versions and tox environments unless a documented dependency constraint requires a change.
- **FR-004**: Unsupported Python 3.15 platform configurations MUST be explicit and explain the dependency limitation.
- **FR-005**: `walk_modules_iter` MUST continue to yield the requested module and discoverable submodules under Python 3.15.
- **FR-006**: `walk_modules_iter` MUST preserve deferred import-error behavior when the returned generator is consumed.
- **FR-007**: Existing command discovery and spider discovery behavior MUST remain compatible with Python 3.10 through 3.15.
- **FR-008**: The project MUST expose Python 3.15 support metadata only when the feature is intended to claim official support; otherwise the CI job MUST be documented as compatibility testing.

### Key Entities

- **CI matrix entry**: A runner, interpreter version, tox environment, and optional coverage flag used by a workflow.
- **Compatibility-sensitive operation**: A public or internal behavior that can vary across interpreter versions, in this feature primarily module discovery.
- **Candidate test**: A repository test file or test symbol that exercises the changed behavior directly or through a production consumer.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The designated Python 3.15 job completes successfully on the supported Linux configuration.
- **SC-002**: All direct module-walker tests pass on Python 3.10 through Python 3.15.
- **SC-003**: Command-discovery and spider-discovery test suites pass on Python 3.15 without changing their expected user-visible behavior.
- **SC-004**: Existing Python 3.10 through Python 3.14 CI entries remain present and runnable.
- **SC-005**: Any platform or environment excluded from Python 3.15 testing has a repository-visible reason.

## Assumptions

- Python 3.15 is a prerelease interpreter during this work and therefore requires prerelease installation support.
- Linux is the first CI platform expected to have a usable dependency set.
- Dependency availability, rather than a deliberate Scrapy compatibility boundary, may still exclude some platforms.
- The module-discovery compatibility work must not introduce syntax or APIs unavailable on the minimum supported Python version.
- The existing test layout and tox environment names remain the primary validation surface.
