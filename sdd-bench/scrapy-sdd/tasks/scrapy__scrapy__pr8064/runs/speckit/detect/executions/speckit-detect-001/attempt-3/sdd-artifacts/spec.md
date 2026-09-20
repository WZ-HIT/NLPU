# Feature Specification: open_in_browser ReDoS Regression Test Hardening

**Feature Branch**: `001-open-in-browser-redos-tests`

**Created**: 2026-09-17

**Status**: Draft

**Input**: PR `scrapy/scrapy#8064` — "Fix open_in_browser ReDoS test flakiness and a broken exploit input" (base commit `3857c6906b2da51e12ca6005434512b7704fd659`)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trustworthy ReDoS regression signal (Priority: P1)

A maintainer relies on the `open_in_browser` regression tests to prove that the
regular expressions which were vulnerable to regular expression denial of
service (ReDoS) cannot silently return. Today those tests measure elapsed CPU
time against a fixed budget, so a slow interpreter or a busy CI worker can make
them fail even though the implementation is safe, and a wrongly chosen payload
can make them pass even though a vulnerable pattern is present.

**Why this priority**: A regression test that reports both false failures and
false successes gives no security guarantee for a public entry point that
processes attacker-controlled response bodies.

**Independent Test**: Run the `open_in_browser` regression tests repeatedly on
the current implementation (they must always pass), and run them once against a
temporarily restored vulnerable pattern (they must fail promptly instead of
hanging). No other part of the suite needs to change.

**Acceptance Scenarios**:

1. **Given** the current implementation and any supported interpreter, **When**
   the adversarial-input tests are executed 20 consecutive times on a loaded
   worker, **Then** every run passes with no timing-induced failure.
2. **Given** a reintroduced vulnerable comment-stripping or head-finding
   pattern, **When** the adversarial-input tests run, **Then** at least one of
   them fails within the normal test timeout rather than blocking the worker.
3. **Given** a slow or CPU-throttled worker, **When** the adversarial-input
   tests run, **Then** the outcome does not depend on machine speed.

---

### User Story 2 - Exploit inputs that actually reproduce the vulnerability (Priority: P2)

Each adversarial payload must genuinely drive super-linear work in the specific
pattern it claims to target. A payload that lets the pattern succeed on its
first attempt - for example because a terminator or a newline is placed so that
the lazy match never has to backtrack - is not valid regression coverage even
though it looks adversarial.

**Why this priority**: Payloads are the evidence that the tests can detect the
regression at all; without that evidence the suite can regress to a green
no-op.

**Independent Test**: Compare the payload against the historical patterns cited
in the test comments (`<!--.*?-->` for comment removal and
`(<head(?:>|\s.*?>))` for head detection) and confirm that the amount of work
grows super-linearly with payload size; then confirm the same payload is handled
quickly by the current implementation.

**Acceptance Scenarios**:

1. **Given** the historical comment-removal pattern and the comment payload,
   **When** the payload is matched against that pattern, **Then** the work
   performed grows super-linearly with payload size and this is recorded next
   to the payload.
2. **Given** the historical head-detection pattern and the head payload,
   **When** the payload is matched against that pattern, **Then** the work
   performed grows super-linearly with payload size and this is recorded next
   to the payload.
3. **Given** the current implementation, **When** both payloads are processed,
   **Then** each test finishes well inside a generous budget and returns a
   browser URL as usual.

---

### User Story 3 - Behaviour coverage stays intact (Priority: P3)

While the adversarial tests are reworked, the behavioural guarantees of
`open_in_browser` remain covered: the injected `base` tag is placed after a
doctype, before the head contents, not inside comments, keeps an existing base
URL, text responses use a `.txt` file, and unsupported response types raise
`TypeError`.

**Why this priority**: The hardening work must not trade security coverage for
functional coverage.

**Independent Test**: Run the existing `open_in_browser` behaviour tests in
`tests/test_utils_response.py` unchanged and confirm they still pass.

**Acceptance Scenarios**:

1. **Given** the existing behaviour tests, **When** the suite runs after the
   change, **Then** the same assertions execute and pass without modification.
2. **Given** the `scrapy view` command, which calls `open_in_browser`, **When**
   its integration test opens a served HTML page, **Then** the produced file
   still contains the served body.

---

### Edge Cases

- Payloads of several megabytes must stay within the memory budget of a normal
  CI worker and must not be copied more than necessary.
- Byte patterns and payloads must keep working under `bytes` regular
  expressions where `.` does not match a newline by default; the payload shape
  must not depend on the `DOTALL` flag accidentally.
- Payloads containing NUL bytes must remain valid inputs for the HTTP response
  body and for `re` on byte strings.
- Interpreters slower than the reference CI run (for example a debugging build
  or an alternative runtime) must not turn a passing implementation into a
  failing test.
- The test must not depend on wall-clock sleeps, network access, locale, or
  filesystem performance beyond the temporary file already created by
  `open_in_browser`.
- Repeated runs in the same interpreter process must not be affected by
  interpreter warm-up, cached regular expressions, or the base-URL cache.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The test suite MUST contain automated regression tests that feed
  adversarial HTML bodies to `scrapy.utils.response.open_in_browser`.
- **FR-002**: Each adversarial payload MUST be documented together with the
  historical vulnerable pattern it targets and the reason it produces
  super-linear behaviour for that pattern.
- **FR-003**: The adversarial tests MUST NOT fail because of machine speed or
  worker load; their verdict MUST be reproducible across repeated runs on
  supported interpreters.
- **FR-004**: The adversarial tests MUST fail promptly (within the project's
  normal test timeout) when a matching vulnerable pattern is reintroduced,
  instead of hanging the worker.
- **FR-005**: The adversarial tests MUST still assert that the browser open
  callback receives a `file://` URL, so that they exercise the real code path
  rather than a stubbed one.
- **FR-006**: Existing `open_in_browser` behaviour coverage MUST be preserved:
  base-tag injection position relative to a doctype and the head element,
  comment preservation, existing base URL precedence, `.txt` output for text
  responses, and `TypeError` for unsupported response types.
- **FR-007**: The change MUST be confined to tests and any supporting test
  comments or documentation; production behaviour of `open_in_browser` MUST NOT
  change.
- **FR-008**: The tests MUST run under the repository's existing pytest
  configuration without new dependencies, network access, or extra tooling.

### Key Entities

- **Adversarial response body**: a `bytes` payload crafted to trigger
  backtracking in a historical pattern; carries a size, a shape, and the
  pattern it targets.
- **Historical vulnerable pattern**: the comment-removal pattern
  (`<!--.*?-->`) and the head-detection pattern (`(<head(?:>|\s.*?>))`) that the
  current implementation no longer uses.
- **`open_in_browser` contract**: given a text response, write an adjusted body
  to a temporary file and hand a `file://` URL to the browser callback.
- **Candidate test module**: the repository test files that exercise
  `open_in_browser`, directly or through the `scrapy view` command.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 20 consecutive executions of the affected test module produce
  identical passing outcomes, with zero failures attributable to timing
  variance.
- **SC-002**: For each adversarial payload, a temporary restore of the
  historical pattern makes the corresponding test fail (verified once during
  implementation, evidence recorded in the task notes) - that is, the tests
  demonstrably detect the regression they target.
- **SC-003**: With the current implementation, each adversarial test completes
  in under 200 ms of CPU time on the reference CI runner, and no run exceeds
  the normal per-test timeout.
- **SC-004**: 100% of the pre-existing `open_in_browser` behaviour assertions
  still execute and pass after the change.
- **SC-005**: The change adds no runtime dependency and no production-code
  change (zero non-test source files modified).

## Assumptions

- At the base commit, `scrapy/utils/response.py` already avoids the vulnerable
  patterns (it uses `_DOCTYPE_RE` plus prefix insertion and performs no
  comment-stripping or head-finding regular expression), so this work is
  test-only.
- "The broken exploit input" refers to one of the crafted payloads in
  `tests/test_utils_response.py` (`test_open_in_browser_redos_comment`), which
  does not reliably reproduce backtracking in the pattern its comment names.
- The relevant primary test file is `tests/test_utils_response.py`;
  `tests/test_commands.py::TestViewCommand` is accepted as an indirect
  integration surface because `scrapy view` calls `open_in_browser`.
- Timing-based assertions remain acceptable as long as the budget is generous
  and the payload makes the vulnerable case orders of magnitude slower; no
  advanced tooling (for example a regex engine or step counter) is assumed to
  be available.
- Supported interpreters are those allowed by the project metadata
  (`requires-python = ">=3.10"`), with CPython on Linux as the reference CI
  environment.
- Tests may be executed through the repository's pytest configuration
  (`--reactor=asyncio`) and are not run during this planning phase.
