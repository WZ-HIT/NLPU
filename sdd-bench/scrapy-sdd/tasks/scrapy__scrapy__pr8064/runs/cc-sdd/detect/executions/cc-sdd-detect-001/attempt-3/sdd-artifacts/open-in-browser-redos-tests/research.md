# Research & Design Decisions Template

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical detection draft.

**Usage**:
- Log research activities and outcomes during the detect planning phase.
- Record why candidate test files were selected, with the evidence used.
---

## Summary

- **Feature**: `open-in-browser-redos-tests`
- **Discovery Scope**: Extension of an existing, already-hardened implementation
  (test-side repair only)
- **Key Findings**:
  - `open_in_browser()` lives in `scrapy/utils/response.py` and no longer uses
    the historical comment/head regexes; it matches an optional doctype with
    `_DOCTYPE_RE` and inserts the `<base>` tag after it.
  - `tests/test_utils_response.py` is the only test module in the repository that
    imports `open_in_browser`; every other reference is production code.
  - The ReDoS guard is a CPU-time budget around the call
    (`_assert_open_in_browser_is_fast`, `time.process_time`, budget `0.2`), which
    is exactly the surface the change requests describe as flaky.
  - Two payload tests exist: `test_open_in_browser_redos_comment`
    (`b"-><!--\x00" * 250_000 + b"->\n<!---->"`) and
    `test_open_in_browser_redos_head` (`b"<head\t" * 80_000`).
  - No test was executed while producing this draft (detect-stage policy).

## Research Log

### Where is the change concentrated?

- **Context**: The change requests describe fixes to ReDoS *tests* for
  `open_in_browser`, plus a broken exploit input.
- **Sources Consulted**: repository tree at base commit
  `3857c6906b2da51e12ca6005434512b7704fd659`,
  `scrapy/utils/response.py`, `tests/test_utils_response.py`,
  `docs/news.rst` (release notes referencing earlier `open_in_browser` fixes).
- **Findings**: the production function already implements the hardened,
  linear-time `<base>` insertion; the adversarial payload tests and their timing
  helper are the only ReDoS-relevant test code.
- **Implications**: the candidate set is a single test module; no production
  change is required by this spec.

### Which test files touch the changed surface?

- **Context**: The detect stage must produce repository-relative test paths.
- **Sources Consulted**: `grep` over `scrapy/` and `tests/` for
  `open_in_browser`, `get_base_url`, `get_meta_refresh`,
  `response_status_message`, and `scrapy.utils.response`.
- **Findings**:
  - Importers of `scrapy.utils.response`: `scrapy/http/response/text.py`,
    `scrapy/selector/unified.py`, `scrapy/linkextractors/lxmlhtml.py`,
    `scrapy/commands/view.py`, `scrapy/shell.py`,
    `scrapy/downloadermiddlewares/redirect.py`,
    `scrapy/downloadermiddlewares/retry.py`.
  - Test modules importing the module: `tests/test_utils_response.py` only.
  - Adjacent test modules that exercise importers indirectly:
    `tests/test_commands.py` (`view` command), `tests/test_command_shell.py`,
    `tests/test_http_response_text.py`, `tests/test_selector.py`,
    `tests/test_linkextractors.py`,
    `tests/test_downloadermiddleware_redirect_metarefresh.py`.
- **Implications**: only `tests/test_utils_response.py` is a candidate for this
  change; the adjacent modules stay out of scope because neither the production
  behaviour nor their inputs are touched.

### Historical vulnerability context

- **Context**: The comment/head payload tests reference the recheck playground.
- **Sources Consulted**: in-repo test comments, `docs/news.rst` entries about
  `open_in_browser` regex fixes and the cc65-xxvf-f7r9 advisory.
- **Findings**: the patterns the payloads guard are `/<!--.*?-->/` (comment
  removal) and `/(<head(?:>|\s.*?>))/` (head detection); both are absent from
  the current implementation.
- **Implications**: the payloads must stay valid witnesses for those patterns or
  the regression guard becomes decorative.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Test-only repair | Adjust budget and payload in the existing module | Smallest possible diff; keeps coverage | Relies on payload quality | Selected |
| Move tests to a dedicated module | New ReDoS test file | Clear separation | Duplicate fixtures, larger diff, new file | Rejected |
| Assert on regex internals | Test the compiled patterns directly | Deterministic | Couples tests to implementation details | Rejected |

## Design Decisions

### Decision: Keep the CPU-time guard, retune it

- **Context**: The 0.2 s CPU budget trips on slow or loaded CI hosts.
- **Alternatives Considered**:
  1. Keep wall-clock timing and raise the budget.
  2. Switch to a stronger payload and keep CPU-time measurement.
- **Selected Approach**: keep `time.process_time` (immune to scheduling delays),
  enlarge the adversarial payload so a vulnerable implementation is clearly
  super-linear, and assert a budget that leaves a wide safety margin for a
  linear implementation.
- **Rationale**: matches the change request ("test flakiness") without weakening
  the regression guard.
- **Trade-offs**: larger payloads cost a little more memory in the test process.
- **Follow-up**: re-check the budget on a slow interpreter.

### Decision: Treat the exploit payloads as contract

- **Context**: One payload is reported as broken, i.e. it does not drive the
  historical pattern into pathological backtracking.
- **Alternatives Considered**:
  1. Delete the ineffective payload.
  2. Replace it with a payload known to trigger the pattern.
- **Selected Approach**: replace it with a witness payload and keep the source
  reference comment.
- **Rationale**: the regression guard must fail against the vulnerable pattern.
- **Trade-offs**: payloads are opaque; inline comments carry the explanation.
- **Follow-up**: verify the payload against the historical pattern in review.

## Risks & Mitigations

- Timing budgets can still be tight on very slow interpreters — mitigation: keep
  the margin large relative to a linear implementation's cost.
- Payload constants can drift from the pattern they guard — mitigation: keep the
  pattern and source in the comment above each payload.
- Behaviour tests could be replaced while chasing flakiness — mitigation:
  Requirement 3 pins the existing coverage.

## References

- `scrapy/utils/response.py` — `open_in_browser`, `_DOCTYPE_RE`, `get_base_url`.
- `tests/test_utils_response.py` — ReDoS payload tests and behaviour tests.
- `docs/news.rst` — earlier `open_in_browser` regex fixes and the
  cc65-xxvf-f7r9 security advisory reference.
- <https://makenowjust-labs.github.io/recheck/playground/> — source of the
  exploit payloads cited in the test comments.
