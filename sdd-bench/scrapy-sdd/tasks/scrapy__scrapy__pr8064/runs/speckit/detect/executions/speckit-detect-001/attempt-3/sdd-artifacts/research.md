# Research: open_in_browser ReDoS Regression Test Hardening

All findings come from static inspection of the checkout at base commit
`3857c6906b2da51e12ca6005434512b7704fd659`. No tests were executed (the
planning run is test-free by policy: `SDD_AGENT_NO_TESTS=1`).

## D1: Which tests exercise `open_in_browser`?

- Decision: `tests/test_utils_response.py` is the primary candidate;
  `tests/test_commands.py::TestViewCommand` is the only indirect candidate.
- Rationale: a repository-wide search for `open_in_browser` finds it in
  `scrapy/utils/response.py` (definition), `scrapy/commands/view.py`,
  `scrapy/shell.py`, and in tests only in `tests/test_utils_response.py`, which
  imports it directly at line 14 and uses it in 12 tests. `scrapy view` calls it
  (`scrapy/commands/view.py:28`), and `TestViewCommand.test_view`
  (`tests/test_commands.py:687`) runs that command end to end against the
  `mockserver`, so it exercises the same code path through the CLI.
- Alternatives considered: coverage-driven collection (rejected: tests cannot
  be run in this phase); including `tests/test_command_shell.py` (rejected: it
  contains no `view`/`open_in_browser` references at this commit).

## D2: Why are the ReDoS assertions flaky?

- Decision: the flakiness source is the fixed CPU-time budget in
  `_assert_open_in_browser_is_fast` (`tests/test_utils_response.py:216`), which
  compares `process_time()` deltas against `max_cpu_time = 0.2` after calling
  `open_in_browser` on the payload.
- Rationale: `process_time()` measures CPU time, not wall time, but the budget is
  still an absolute threshold on the same machine that runs the regex engine.
  A slower interpreter (debug build, PyPy, CPU-throttled CI worker, sanitizer
  build) can exceed 0.2 s on a safe implementation and report a false failure,
  while a fast machine widens the margin and can hide a payload that is not
  actually adversarial.
- Alternatives considered:
  (a) keep a timing assertion but widen the budget and shrink payload size
  (reduces both false positives and detection power);
  (b) assert super-linear scaling by timing two payload sizes (still
  speed-sensitive, more variables);
  (c) move the check into a subprocess with a hard timeout (detects hangs
  robustly, but adds process-management complexity and still depends on the
  machine being fast enough to finish the safe case);
  (d) verify the payload against the historical pattern with a deterministic
  step/attempt counter or by asserting the match result (no timing at all).
  The plan recommends combining a generous budget for the safe case with a
  documented, verified payload; (d) is the most robust option if the
  implementation phase wants to drop timing entirely.

## D3: Why is one exploit input broken?

- Decision: treat the comment payload
  `b"-><!--\x00" * 250_000 + b"->\n<!---->"` (`tests/test_utils_response.py:233`)
  as the suspect input, and require the implementation phase to verify each
  payload against the pattern named in its comment.
- Rationale (reasoned hypothesis, needs confirmation by the implementer): for a
  `bytes` pattern, `.` does not match `\n` unless `DOTALL` is set. A payload only
  forces quadratic scanning if every candidate `<!--` start position must scan
  forward and fail. The payload ends with `b"->\n<!---->"`, whose trailing
  `<!---->` contains an immediate `<!--` + `-->` match; with a `DOTALL` pattern
  the first start position also matches across the terminating `-->`, so the
  whole payload resolves in one pass and the test passes even with a vulnerable
  pattern. The exact historical pattern is the one documented in the test
  comments (`<!--.*?-->`), so the payload's validity depends on the newline and
  terminator placement rather than on payload length.
- Alternatives considered: reproducing the pre-fix implementation from git
  history (rejected: the checkout is shallow - a single commit - and network
  access is disabled, so the historical code cannot be retrieved here).

## D4: What must not change?

- Decision: keep every existing `open_in_browser` behaviour assertion intact.
- Rationale: `tests/test_utils_response.py` covers base-tag injection position
  relative to doctype and head contents (`test_inject_base_url`,
  `test_open_in_browser_injects_base_before_head_contents`), comment
  preservation (`test_open_in_browser_preserves_html_comments`), base-URL
  precedence (`test_open_in_browser_keeps_base_url_of_response`), the
  comment-only base case, `.txt` output for `TextResponse`, and `TypeError` for
  plain `Response`. Production code at the base commit already avoids the
  vulnerable regexes (`_DOCTYPE_RE` plus prefix insertion in
  `scrapy/utils/response.py`).
- Alternatives considered: rewriting the behaviour tests (rejected: out of
  scope for a test-flakiness fix and it would weaken the safety net).

## D5: Verification approach for the implementation phase

- Decision: validate by running only the affected module
  (`python -m pytest tests/test_utils_response.py`) repeatedly, and once with a
  temporarily restored vulnerable pattern to confirm the payloads fail fast.
- Rationale: repeated runs surface flakiness; the deliberate-regression run is
  the only available evidence that a timing-free assertion still detects the
  vulnerability.
- Note: neither run is performed in this planning phase.
