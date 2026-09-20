# Feature Specification: Fix open_in_browser ReDoS Test Flakiness and a Broken Exploit Input

**Feature Branch**: `001-fix-redos-test-flakiness`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "Fix open_in_browser ReDoS test flakiness and a broken exploit input" (repository `scrapy/scrapy`, pull request 8064, base commit `3857c6906b2da51e12ca6005434512b7704fd659`)

## Context

`scrapy.utils.response.open_in_browser` renders a response into a temporary
file and hands it to a browser. Earlier versions located the `<head>` element
and stripped HTML comments with regular expressions; those patterns were
replaced because crafted response bodies could drive them into catastrophic
backtracking (ReDoS). The current implementation injects the base tag without
searching for `<head>` and without stripping comments.

Regression tests were added for that fix. Two of them
(`test_open_in_browser_redos_comment`, `test_open_in_browser_redos_head`) push a
very large crafted body through `open_in_browser` and assert that the call
finishes inside a small CPU-time budget. That design produces two problems:

1. The wall/CPU-time budget is a machine-speed assumption, so the tests can
   fail on slow or heavily loaded workers even though the implementation is
   correct (flakiness).
2. At least one of the crafted bodies does not actually attack the pattern it
   claims to attack, so the regression test can pass against a vulnerable
   implementation as well (a vacuous test with a "broken exploit input").

This feature covers making the ReDoS regression coverage deterministic and
making every exploit body genuinely detect the pattern it targets, without
changing user-visible viewer behavior.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - ReDoS regression tests never fail because of machine speed (Priority: P1)

A maintainer runs the `open_in_browser` tests on a fast laptop, on a
CPU-throttled CI container, and on a slow debug build of Python. The ReDoS
regression tests pass every time, because the pass/fail decision no longer
depends on how fast the machine happens to be, only on whether the
implementation still uses the removed catastrophic patterns.

**Why this priority**: Flaky tests erode trust in the suite, cause needless
re-runs, and can hide real regressions. This is the primary motivation of the
pull request and delivers value on its own.

**Independent Test**: Run the ReDoS test selection repeatedly on the fixed
implementation, including under artificial CPU contention; every run passes.
Then reinstate the previously removed vulnerable patterns in a scratch copy and
run the same selection; at least one ReDoS test fails.

**Acceptance Scenarios**:

1. **Given** the fixed implementation and a loaded/throttled worker, **When**
   the ReDoS regression tests run 20 times in a row, **Then** all 20 runs pass.
2. **Given** an implementation whose comment handling is driven by the removed
   `<!--.*?-->`-style pattern, **When** the comment ReDoS test runs, **Then**
   the test fails (the regression is detected).
3. **Given** an implementation whose head handling is driven by the removed
   `<head(?:>|\s.*?>)`-style pattern, **When** the head ReDoS test runs,
   **Then** the test fails (the regression is detected).
4. **Given** the fixed implementation, **When** the whole
   `tests/test_utils_response.py` module runs, **Then** every test still passes
   and no test is skipped or removed to achieve that.

---

### User Story 2 - Exploit bodies genuinely exercise the patterns they guard against (Priority: P2)

A maintainer reviews the ReDoS regression tests and can confirm that each
crafted body actually forces the corresponding removed pattern to do
super-linear work. A body that supplies the terminating delimiter early (and
therefore lets the vulnerable pattern match quickly) counts as a defect and is
replaced by a body that keeps the vulnerable pattern searching.

**Why this priority**: A regression test with a broken exploit input is worse
than no test at all: it advertises protection that does not exist. This is
required for User Story 1's guarantee to be meaningful, but it is a narrower
change.

**Independent Test**: For each exploit body, evaluate the removed pattern and
the current implementation on the same body in an isolated harness; the removed
pattern must be dramatically slower (orders of magnitude, or beyond a generous
fixed budget) while the shipped implementation stays far below the budget.

**Acceptance Scenarios**:

1. **Given** the comment exploit body, **When** it is evaluated against the
   removed comment pattern, **Then** the pattern exceeds a generous cost budget
   instead of matching early.
2. **Given** the head exploit body, **When** it is evaluated against the removed
   head pattern, **Then** the pattern exceeds a generous cost budget.
3. **Given** either exploit body, **When** it is evaluated against the shipped
   implementation, **Then** the body is processed well inside the budget.

---

### User Story 3 - Viewer behavior is unchanged (Priority: P3)

A user views a response with `scrapy view` or `open_in_browser`. The injected
base tag still points at the response URL, comments in the document survive,
`<head>`-like text inside comments is still ignored for base-tag placement,
text responses still open with a `.txt` path, and unsupported response types
still raise the same error.

**Why this priority**: It is the safety net for the two stories above; it
protects existing, already-correct behavior rather than adding new behavior.

**Independent Test**: Run the full `tests/test_utils_response.py` module and
the `view`-command tests in `tests/test_commands.py`; all pre-existing
assertions pass unchanged.

**Acceptance Scenarios**:

1. **Given** an HTML response containing comments (including conditional
   comments) with `<head>`/`<base>` text inside them, **When** it is opened,
   **Then** exactly one base tag for the response URL is injected and comments
   are preserved.
2. **Given** an HTML response that starts with a doctype declaration, **When** it
   is opened, **Then** the base tag is placed after the doctype.
3. **Given** a text response, **When** it is opened, **Then** the browser is
   handed a `.txt` path; **Given** a plain binary `Response`, **When** it is
   opened, **Then** a `TypeError` is raised.

### Edge Cases

- Crafted bodies that contain a closing delimiter (so a lazy pattern matches
  early and terminates) must not be used as ReDoS evidence.
- Crafted bodies that contain no closing delimiter force a lazy pattern to scan
  to end of input from every candidate start position; this is the shape that
  must be preserved.
- Measurement noise from process-wide CPU counters, container CPU quotas, and
  garbage collection must not decide the outcome of the regression tests.
- Doctype present with unusual casing/whitespace versus absent; content before
  `<html>`; `<head>` with attributes; a `<header>` element that must not be
  mistaken for `<head>`.
- Comment-only `<head>`/`<base>` markup, nested/conditional comments, and
  documents with no `<head>` at all.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `open_in_browser` ReDoS regression tests MUST have a
  deterministic pass/fail criterion that does not depend on the absolute speed
  of the machine or interpreter running them.
- **FR-002**: The ReDoS regression tests MUST still fail when the removed
  catastrophic patterns are reinstated in the implementation.
- **FR-003**: Every crafted body used by a ReDoS regression test MUST be shown
  to drive its target removed pattern beyond a generous cost budget; bodies
  that terminate the target pattern early MUST be replaced or corrected.
- **FR-004**: `open_in_browser` MUST preserve HTML comments in the rendered
  document.
- **FR-005**: `open_in_browser` MUST inject exactly one base tag, derived from
  the response URL/base, after any doctype declaration and before head
  contents.
- **FR-006**: Text responses MUST continue to be rendered with a `.txt` path
  and non-text responses MUST continue to raise `TypeError`.
- **FR-007**: The tests MUST run without network access and without opening a
  real browser.
- **FR-008**: The change MUST be limited to the test suite unless a genuine
  defect is found in the shipped base-tag injection behavior; any such defect
  must be documented and covered by a new test rather than silently absorbed.

### Key Entities

- **Exploit body**: A crafted response body used to prove that a removed
  pattern is no longer reachable in the implementation.
- **Cost budget**: The deterministic criterion that separates "vulnerable
  pattern" from "shipped implementation" for a given exploit body.
- **Rendered viewer output**: The temporary file contents handed to the
  browser, including the injected base tag and preserved comments.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The ReDoS regression tests pass 100% of at least 20 consecutive
  runs on the fixed implementation, including runs under artificial CPU
  contention.
- **SC-002**: Against the removed patterns, each exploit body exceeds the
  budget by at least two orders of magnitude; against the shipped
  implementation it stays below 10% of the budget.
- **SC-003**: Reinstate-the-vulnerable-pattern checks fail for both the comment
  and head scenarios (0 of 2 falsely pass).
- **SC-004**: No pre-existing assertion in `tests/test_utils_response.py` or in
  the `view`-command tests is removed, skipped, or relaxed to obtain the above.
- **SC-005**: Zero flaky-run reports for these tests in CI over one release
  cycle.

## Assumptions

- The shipped regex-free implementation of `open_in_browser` is correct; this
  change is about proving that, not about re-designing it.
- `pytest` with the repository's configured options is the test runner, and the
  affected tests must remain runnable as a single module
  (`tests/test_utils_response.py`) and as a single selection.
- CI workers may be slower than developer machines and may share CPU with other
  workloads, so any residual timing assertion must carry a wide margin or be
  replaced by a structural check.
- The `view` command (`tests/test_commands.py`) is the practical end-to-end
  entry point that exercises `open_in_browser`, so it stays part of the
  verification surface.
