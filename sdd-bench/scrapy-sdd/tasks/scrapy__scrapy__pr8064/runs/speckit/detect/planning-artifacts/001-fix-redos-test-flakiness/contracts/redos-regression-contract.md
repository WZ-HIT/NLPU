# Interface Contract: open_in_browser ReDoS Regression Coverage

This project exposes a Python library API, so the relevant "interface" for this
feature is the contract that the regression tests provide to reviewers and to
future maintainers of `scrapy.utils.response.open_in_browser`. Automated tests
verify this contract; no production interface changes.

## C1 — Public behaviour under test (unchanged)

- `open_in_browser(response, _openfunc=...)` accepts an `HtmlResponse` or
  `TextResponse` and calls `_openfunc` with a `file://` URL of a temporary file.
- HTML responses get a `.html` temporary file; other text responses get `.txt`;
  a plain `Response` raises `TypeError`.
- The rendered HTML contains exactly one injected base tag derived from the
  response URL, positioned after any doctype declaration and before head
  content, and HTML comments are preserved.

## C2 — Exploit body validity predicate

For every ReDoS regression body `B` and its target removed pattern `P`:

```
P applied to B  MUST NOT produce an early successful match
```

Equivalently, the body must force the historical pattern to scan to the end of
input (or fail outright). A body that supplies P's terminating delimiter — for
example a trailing `<!---->` providing `-->` to `<!--.*?-->` — violates the
contract and MUST be replaced. This is asserted deterministically in the test.

## C3 — Cost criterion

The regression assertion MUST decide pass/fail from a machine-independent
signal: the measured growth of the shipped implementation between a base body
size and a larger multiple of it, bounded by a generous sub-quadratic factor,
with an absolute limit used only as a wide smoke check. The assertion MUST NOT
depend on a machine-tuned constant such as a fixed few-hundred-millisecond CPU
budget.

## C4 — Coverage obligations

- Both removed patterns (`comment-stripping`, `head-lookup`) have at least one
  valid exploit body and one regression test (FR-002).
- Reinstating either removed pattern in a scratch copy of the implementation
  makes the corresponding regression test fail (SC-003).
- Every pre-existing assertion in `tests/test_utils_response.py` and in the
  `view`-command tests is retained (SC-004).
- The tests run without network access and without a real browser (FR-007).

## C5 — Verification surface

Primary: `tests/test_utils_response.py`.
End-to-end: `tests/test_commands.py` (`TestViewCommand`), which drives
`scrapy view` against a local mock server with a recording browser script.
