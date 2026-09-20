## Context

See `proposal.md` - Why. The current regression helper in
`tests/test_utils_response.py` builds a large `HtmlResponse`, calls
`open_in_browser`, and compares `time.process_time()` against a 0.2-second
budget. Process-wide CPU accounting can include unrelated threads in a shared
pytest process, while the tight budget leaves little room for slower
interpreters. The comment exploit input also ends with `<!---->`, which
provides a `-->` terminator and lets a vulnerable pattern complete after one
long scan.

## Goals / Non-Goals

**Goals:**

- Preserve a regression test that fails for catastrophic backtracking in the
  old comment and `<head>` patterns, but not for ordinary execution on slow
  workers.
- Make the comment input exercise repeated failed searches rather than one
  successful match.
- Keep the change confined to test code.

**Non-Goals:**

- Changing `open_in_browser`, its public contract, or runtime dependencies.
- Reintroducing regular expressions into the implementation.
- Adding a general ReDoS-detection framework.

## Decisions

- Measure only the calling thread's CPU time and widen the acceptance budget
  enough to accommodate slow interpreters and shared CI workers. The inputs
  remain large enough that the vulnerable patterns require orders of magnitude
  more work than the safe implementation.
- Keep an absolute timing guard rather than a ratio measured at test time. A
  same-test baseline would add parsing and allocation noise, while the old
  vulnerable patterns differ from the safe line-oriented implementation by a
  much larger margin than the proposed budget.
- Remove the trailing `<!---->` terminator from the comment exploit body. The
  corrected body must contain many `<!--` starts but no `-->`, forcing the old
  `<!--.*?-->` pattern to scan from each start to the end of the input.
- Leave the `<head>` exploit body unterminated for the same reason: it must not
  introduce a cheap successful match for the old `<head(?:>|\s.*?>)` pattern.

Alternatives considered:

- Removing timing assertions entirely would make the regression test unable to
  detect a reintroduced vulnerable pattern.
- Using wall-clock time would make the test more sensitive to scheduler and
  I/O noise.
- Comparing against a vulnerable regex implementation kept in the test would
  duplicate implementation detail and still require a timing comparison.

## Risks / Trade-offs

- A too-generous threshold could miss a moderately slow implementation ->
  keep the exploit bodies large enough that the old patterns exceed multiple
  seconds, leaving the threshold well below the vulnerable runtime.
- A too-tight thread-time threshold could still flake on very slow platforms ->
  use a one-second budget and verify the measured safe runtime has a wide
  margin during implementation.
- The exploit body no longer contains a valid comment -> the test is explicitly
  a malformed-input regression case; comment-preservation behavior remains
  covered by `test_open_in_browser_preserves_html_comments`.

## Migration Plan

No deployment or data migration is required. Revert the test changes if the
new timing strategy proves unreliable on a supported platform.
