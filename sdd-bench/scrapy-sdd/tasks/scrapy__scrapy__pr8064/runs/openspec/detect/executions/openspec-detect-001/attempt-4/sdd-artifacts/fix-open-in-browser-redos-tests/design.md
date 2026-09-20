## Context

See `proposal.md` - Why.

Current state, as observed in the repository at the base commit:

- `scrapy/utils/response.py` builds the modified body with a single
  `_DOCTYPE_RE.match(body)` call (`rb"\s*<!doctype[^<>]*>"`) and then splices
  the base tag in. It no longer removes comments or searches for the head
  element, so no pattern that the two documented exploits targeted is
  evaluated any more.
- `tests/test_utils_response.py` guards that with
  `_assert_open_in_browser_is_fast()`, which measures `process_time()` around a
  single `open_in_browser()` call and asserts the result is below a fixed
  `max_cpu_time = 0.2` seconds.
- The two inputs are `b"-><!--\x00" * 250_000 + b"->\n<!---->"` (≈ 2 MB) and
  `b"<head\t" * 80_000` (≈ 0.5 MB). Measured on the base commit, the current
  implementation handles those bodies in ≈ 8 ms and ≈ 1 ms respectively.
- Measured against the historical patterns they document, both inputs are
  genuinely catastrophic but far larger than they need to be: `<!--.*?-->`
  takes ≈ 0.51 s on a 28 KB prefix of the comment input, and
  `(<head(?:>|\s.*?>))` takes ≈ 1.59 s on a 48 KB prefix of the head input.

Constraints: this change is test-only, must not alter `open_in_browser`
behaviour or any public API, and must leave the other `open_in_browser` tests
(`test_open_in_browser`, `test_inject_base_url`, the base-URL, comment, text
response, and `TypeError` tests) asserting exactly what they assert today.

## Goals / Non-Goals

**Goals:**

- Make the adversarial-input guard reach a decision that is independent of the
  absolute speed of the machine and interpreter running the suite.
- Make each adversarial input demonstrably an exploit for the pattern it
  documents, so the input cannot silently become meaningless.
- Keep the guard's own runtime small enough that it is unremarkable inside a
  normal test session.

**Non-Goals:**

- Changing `scrapy/utils/response.py`, its signatures, or its output.
- Adding a general performance-testing harness or a benchmark suite for Scrapy.
- Covering `get_base_url`, `get_meta_refresh`, or `response_status_message`
  with similar guards.

## Decisions

### 1. Decide pass/fail from relative scaling + coarse hang ceiling, not an absolute budget

Measure the same body processed once at size `N` and once at size `2N` with
`process_time()`, and require the doubling factor to stay well below the
quadratic regime (a small bound such as 3x for a doubling; a catastrophic
backtracking implementation grows ≈ 4x per doubling and is orders of magnitude
slower in absolute terms). Keep a single coarse absolute ceiling (seconds, not
tenths of a second) purely as a hang guard so a pathological regression fails
quickly instead of blocking CI.

Alternatives considered:

- *Raise `max_cpu_time`* - simplest, but the criterion is still an absolute
  speed threshold; it just moves the flakiness boundary.
- *Drop timing and assert output only* - removes flakiness but also removes the
  only regression signal for catastrophic backtracking.
- *Compare against a benign baseline body of the same size* - also
  machine-relative, but the baseline body's cost depends on unrelated work
  (temp file writing, base-URL parsing), so the ratio is noisier than the
  doubling ratio of the adversarial body itself.

### 2. Make the exploit inputs self-validating and smaller

Keep both adversarial inputs (they are the documented recheck-playground
inputs) but shrink them to the smallest length that still shows super-linear
behaviour on the historical pattern, and have the test verify that property
itself: run the historical pattern on a short prefix of the same input at two
sizes and assert super-linear growth before asserting that
`open_in_browser` is fast. This keeps the input honest even though the current
implementation evaluates no comment or head pattern at all, and it cuts the
bodies from ≈ 2 MB / 0.5 MB to tens of kilobytes.

Alternatives considered:

- *Trust the comment above the input* (today's behaviour) - the comment claims
  an exploit for a pattern the code no longer contains, and nothing detects
  when the input stops being one.
- *Delete the inputs and rely on the behavioural tests* - leaves no protection
  if a comment-stripping or head-finding step is reintroduced later.

### 3. Keep the guard in the existing test module and helper name

`_assert_open_in_browser_is_fast()` stays in `tests/test_utils_response.py`
with its current signature (`body: bytes`) so the two `test_open_in_browser_redos_*`
tests keep calling it, and the fix stays reviewable as a test-quality change
rather than a new module.

## Risks / Trade-offs

- [Relative timing is still noisy under heavy interference] → measure CPU time
  (not wall clock), process each size more than once and take the minimum,
  and set the ratio bound so that only an order-of-magnitude regression (≈ 4x
  per doubling, continuing) can breach it.
- [A generous ratio bound could miss a mild regression] → the self-validation
  step ties the inputs to super-linear behaviour of the historical patterns, so
  a reintroduced backtracking step shows up as a large, not marginal, change.
- [Smaller inputs weaken the guard] → inputs are chosen at the smallest size
  that still spends ~0.1-0.5 s in the historical pattern, keeping a large
  margin between the vulnerable and the current implementation.
- [The guard no longer measures the exact code path that once regressed] → the
  spec still requires bounded work on adversarial bodies, and the
  self-validation step keeps the inputs meaningful, so a future implementation
  that reintroduces regex-based comment or head handling is detected.

## Migration Plan

Test-only change; no deployment, data migration, or rollback beyond reverting
the test file. The reworded tests replace the flaky ones rather than adding new
failure modes for users.

## Open Questions

- Whether the doubling-ratio helper should be factored out for reuse by other
  ReDoS guards in the suite is left to a follow-up change; it does not affect
  the specs or the task breakdown here.
