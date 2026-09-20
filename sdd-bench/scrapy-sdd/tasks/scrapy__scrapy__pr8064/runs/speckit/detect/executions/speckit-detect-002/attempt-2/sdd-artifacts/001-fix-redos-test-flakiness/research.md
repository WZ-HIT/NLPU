# Phase 0 Research: Fix open_in_browser ReDoS Test Flakiness and a Broken Exploit Input

All unknowns from the Technical Context are resolved below. No new dependency
and no network access is required by any decision.

## D1: How the regression decision stays machine independent

**Decision**: Split the guarantee into two parts.

1. A *validity* predicate for the exploit body that is fully deterministic
   (see D2).
2. A *cost* check that does not rely on an absolute wall-clock budget: measure
   the shipped implementation at a base size and at a multiple of that size on
   the same machine in the same process, and require the growth factor to stay
   below a generous sub-quadratic bound. Keep an absolute budget only as a
   coarse smoke check with a wide margin, derived from the same measurement
   rather than hardcoded.

**Rationale**: A ratio between two measurements taken moments apart on the same
worker cancels machine speed, interpreter build, and container CPU quota, which
is exactly the source of the current flakiness. Quadratic behaviour of the
removed patterns grows by roughly the square of the size multiplier, so the
bound stays far from both "linear and slow" and "quadratic and fast".

**Alternatives considered**:

- *Widen the existing `max_cpu_time` constant.* Rejected: it only moves the
  flakiness threshold; a slow enough or noisy enough worker still fails, and a
  fast worker still cannot distinguish a quadratic implementation from a linear
  one at the sizes that keep the suite quick.
- *Assert on the source text of the implementation (no vulnerable pattern
  present).* Rejected as the primary signal: it is deterministic but tests the
  spelling of the implementation rather than its behaviour, and it would fail
  for an equivalent but differently written pattern.
- *Add a third-party ReDoS analyzer.* Rejected: a new test dependency with no
  runtime benefit, and it does not exercise the shipped code path.

## D2: How an exploit body is proven to be a real exploit

**Decision**: Require every ReDoS body to satisfy a deterministic structural
predicate against the pattern it targets: applying the removed pattern to the
body must not produce an early successful match (the pattern must fail to match,
or match only after scanning to the end of the body). Bodies that supply the
closing delimiter (for example a trailing `<!---->`, which contains `-->`) are
rejected and replaced, because they let the vulnerable lazy pattern terminate
after a single forward scan.

**Rationale**: Catastrophic backtracking for a lazy pattern such as
`<!--.*?-->` needs the pattern to *fail* (or to be forced to restart) after a
long forward scan. The current comment body appends `b"->\n<!---->"`, which
provides a genuine `-->`, so the vulnerable pattern matches once and the test
passes even against the vulnerable implementation. The predicate is cheap,
exact, and independent of machine speed, so it can be asserted directly in the
test.

**Alternatives considered**:

- *Assert with a stopwatch that the removed pattern is slow.* Rejected: it
  reintroduces the very machine dependence this feature removes.
- *Assert the body contains no `-->` substring.* Rejected as too specific to
  one pattern spelling; the predicate should be expressed against the pattern
  being guarded, so it also covers the head pattern.
- *Drop the comment scenario.* Rejected: it is a real historical defect and
  belongs in the suite once its body is corrected.

## D3: Body sizing

**Decision**: Keep bodies large enough that a quadratic implementation cannot
finish inside the suite's patience, but derive the repetition counts from the
scaling measurement (D1) instead of the current fixed `250_000` / `80_000`
repetitions, and keep the assembled body small enough to stay well inside CI
memory and time limits.

**Rationale**: Fixed repetition counts are a second, hidden machine assumption:
they were tuned for one machine's speed and memory. Tying the size to the
measured linear behaviour keeps the same detection power with less variance.

**Alternatives considered**: Very large fixed bodies (rejected: memory and time
variance), or tiny bodies (rejected: cannot separate linear from quadratic).

## D4: Where the tests live

**Decision**: Keep the unit-level regression tests in
`tests/test_utils_response.py`, sharing the existing
`_assert_open_in_browser_is_fast`-style helper, and keep end-to-end coverage in
`tests/test_commands.py` (`TestViewCommand`).

**Rationale**: Both files already exercise `open_in_browser`; no new module is
needed, and reviewers of the original ReDoS work already look here.

**Alternatives considered**: A new dedicated module for ReDoS tests (rejected:
splits closely related assertions and adds review surface for no gain).

## D5: Product code involvement

**Decision**: Treat the shipped regex-free base-tag injection as correct by
default and confine the change to tests. If, while correcting an exploit body,
the shipped behaviour is shown to be wrong for that body, fix it and add a
normal behavioural test for the fix in the same module.

**Rationale**: Matches FR-008 and keeps the pull-request scope reviewable.
