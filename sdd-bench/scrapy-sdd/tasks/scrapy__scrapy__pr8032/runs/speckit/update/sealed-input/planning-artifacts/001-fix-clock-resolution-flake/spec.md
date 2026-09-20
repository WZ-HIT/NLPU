# Feature Specification: Deterministic Response-Based File Path Test

**Feature Branch**: `001-fix-clock-resolution-flake`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "Fix a Windows clock-resolution flake in test_file_path_from_response"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deterministic verdict for a response-based file path (Priority: P1)

A maintainer runs the Scrapy test suite, including on Windows where the wall
clock has a coarse resolution. The test that exercises a files-pipeline
subclass whose path is derived from the download response must reach the same
assertion outcome on every run: the item result must be reported as
`downloaded` with a response-derived extension.

**Why this priority**: This is the only broken behavior. The test currently
fails intermittently on platforms whose clock does not advance between two
consecutive reads, which makes CI red for reasons unrelated to the code under
test.

**Independent Test**: Run the single test repeatedly (and/or on a platform with
a low-resolution clock) and confirm it passes every time with the same
assertions, without any sleep, retry, or timing tolerance.

**Acceptance Scenarios**:

1. **Given** a files pipeline configured so freshness checks cannot mark a
   pre-existing file as up to date, and a store that reports the pre-existing
   file as very recently modified, **When** an item referencing that file is
   processed, **Then** the item result reports `downloaded` and the stored path
   carries the response-derived `.pdf` extension.
2. **Given** a host clock that does not advance between the timestamp reported
   by the store and the moment the freshness decision is made, **When** the
   item is processed, **Then** the outcome is identical to scenario 1 (the file
   is still re-downloaded) rather than being reported as `uptodate`.

---

### User Story 2 - No regression in the neighbouring pipeline tests (Priority: P2)

A maintainer relies on the rest of the files-pipeline test module to still
cover path derivation, custom path overrides, and the up-to-date skip when
expiry is enabled.

**Why this priority**: The fix touches shared test helpers and mock data used
by sibling tests, so it must not silently weaken the module's coverage.

**Independent Test**: Run the whole files-pipeline test module on a platform
with a normal clock and confirm every test still passes.

**Acceptance Scenarios**:

1. **Given** the existing files-pipeline test module, **When** the full module
   is executed after the change, **Then** all tests pass with no skipped
   assertions and no newly added sleeps.

---

### Edge Cases

- The clock reading used for the freshness decision equals the clock reading
  used to build the mocked "last modified" value (the Windows case).
- The mocked "last modified" value lands exactly on the expiry boundary where
  an `uptodate` decision would otherwise be reached.
- The environment has no network access; the test must stay fully simulated.
- The response carries a content type whose extension is absent from the
  URL path, so the extension can only come from the response.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The response-based file path test MUST produce the same
  assertion outcome regardless of the host platform's clock resolution.
- **FR-002**: The test MUST keep exercising a path override that reads the
  download response, and MUST keep asserting that the stored path carries the
  response-derived `.pdf` extension.
- **FR-003**: The test MUST keep verifying that a pre-existing file at the
  response-less path is bypassed while expiry is disabled.
- **FR-004**: The fix MUST be deterministic: no sleeps, retries, polling, or
  timing tolerances may be introduced.
- **FR-005**: The fix MUST NOT weaken or delete assertions from other tests in
  the files-pipeline module.
- **FR-006**: The test MUST remain fully offline and simulated.

### Key Entities *(include if feature involves data)*

- **Response-aware pipeline double**: a files-pipeline subclass whose path
  computation appends an extension taken from a download response header.
- **Store record**: the freshness information (checksum, last-modified
  timestamp) reported for a path that already exists on disk.
- **Item result entry**: the per-file outcome carrying `status` and `path`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The response-based file path test passes on 100% of repeated runs
  on a platform with a low-resolution clock.
- **SC-002**: The test completes without any added wait, and introduces zero
  new flaky outcomes over a representative CI window.
- **SC-003**: 100% of the pre-existing files-pipeline tests continue to pass.
- **SC-004**: Zero new network calls or external dependencies are introduced by
  the change.

## Assumptions

- The flaky platform reported by the issue is Windows, whose system clock is
  documented as having a coarse (~15 ms) resolution.
- Only the nondeterministic freshness decision in this single test is in scope;
  production pipeline behavior is unchanged.
- The store and download are already mocked by the test, so no real I/O needs
  to be added or removed.
- The test module's existing helpers for building the pipeline and preparing
  requests are reused rather than reimplemented.
