# Requirements Document

## Introduction

`scrapy.utils.response.open_in_browser()` rewrites an HTML response body so that a
local browser resolves relative URLs against the response URL. The function is
covered by `tests/test_utils_response.py`, which includes two regression tests
that feed adversarial payloads through the function and assert that the call
stays within a small CPU-time budget, plus a set of behaviour tests that pin the
`<base>` tag injection rules (comments, doctype, head-less HTML, response type
mapping).

The pull request under change requests is scrapy/scrapy#8064, titled
"Fix open_in_browser ReDoS test flakiness and a broken exploit input". It is a
test-only change: the ReDoS-hardened implementation of `open_in_browser()` is
already present at the base commit, but its regression tests are reported as
flaky (a CPU-time budget that trips on slow or loaded machines) and one of the
exploit payloads does not actually exercise the historical vulnerable pattern it
claims to guard.

## Boundary Context

- **In scope**: the ReDoS regression tests for `open_in_browser()`, their timing
  helper, their exploit payloads, and the surrounding `open_in_browser()`
  behaviour tests in `tests/test_utils_response.py`.
- **Out of scope**: changes to the `open_in_browser()` implementation in
  `scrapy/utils/response.py`, changes to `scrapy view` / shell consumers, and
  all other test modules.
- **Adjacent expectations**: the doctype-aware `<base>` insertion contract that
  `tests/test_utils_response.py` encodes must not be weakened, because
  `scrapy/commands/view.py` and `scrapy/shell.py` call `open_in_browser()`
  directly.

## Requirements

### Requirement 1: Deterministic ReDoS regression timing

**Objective:** As a Scrapy maintainer, I want the ReDoS regression tests to
assert the same safety property on every machine, so that CI results are trusted
instead of retried.

#### Acceptance Criteria

1. When `test_open_in_browser_redos_comment` or `test_open_in_browser_redos_head`
   runs on a loaded interpreter, the test shall pass without depending on host
   speed beyond the budget it documents.
2. While a linear-time implementation of `open_in_browser()` is under test, the
   measured CPU time shall stay well below the asserted budget.
3. If a quadratic or catastrophic-backtracking implementation is restored, then
   the regression test shall exceed the asserted CPU-time budget and fail.
4. The timing helper shall measure CPU time rather than wall-clock time, so that
   scheduling delays of the test runner do not affect the result.
5. The payload size and the asserted budget shall be documented in the test
   source so a future maintainer can judge the safety margin.

### Requirement 2: Exploit inputs exercise the historical vulnerable patterns

**Objective:** As a Scrapy maintainer, I want each ReDoS payload to be a genuine
witness for the pattern it guards, so that the regression tests cannot silently
stop testing anything.

#### Acceptance Criteria

1. When the comment-removal payload is executed against the historical
   `/<!--.*?-->/` pattern, the payload shall trigger the pathological
   backtracking that motivated the test.
2. When the head-detection payload is executed against the historical
   `(<head(?:>|\s.*?>))` pattern, the payload shall trigger the pathological
   backtracking that motivated the test.
3. If a payload is reduced, renamed, or replaced, the accompanying comment shall
   state the pattern and the source of the payload.
4. The two ReDoS tests shall remain independent of each other, so that a failure
   identifies which pattern regressed.

### Requirement 3: Existing open_in_browser coverage is preserved

**Objective:** As a Scrapy maintainer, I want the ReDoS work to leave the
functional contract of `open_in_browser()` covered, so that hardening does not
regress output behaviour.

#### Acceptance Criteria

1. The test module shall keep covering `<base>` injection for responses with a
   `<head>` element, with commented-out head content, and with no `<head>`
   element at all.
2. When the response body starts with a doctype declaration, the injected
   `<base>` tag shall be placed after that declaration.
3. Where the response is a plain `TextResponse`, the test module shall keep
   asserting the `.txt` extension, and where the response is a non-text
   `Response`, it shall keep asserting `TypeError`.
4. The test module shall keep covering `get_base_url`, `get_meta_refresh`, and
   `response_status_message`, which live in the same module under test.

### Requirement 4: Candidate test files are identified before any execution

**Objective:** As an SDD detect-stage operator, I want the candidate test files
for this pull request recorded as planning output, so that the later verify stage
knows exactly which files to run.

#### Acceptance Criteria

1. When the detect stage completes, the planning directory shall contain a
   detection draft listing each candidate test path with repository-relative
   paths, symbols, and a reason.
2. While the detect stage runs, no test file and no project source file shall be
   modified and no test suite shall be executed.
3. The candidate list shall be derived from the import and call graph of the
   changed module rather than from a guess about the change.
