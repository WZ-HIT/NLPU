## Purpose

Keeps the `open_in_browser` response helper responsive on adversarial HTML
bodies and keeps the regression tests that guard that responsiveness
deterministic and meaningful.

## ADDED Requirements

### Requirement: Bounded work on adversarial HTML bodies

When `open_in_browser` prepares an HTML response whose body is built from
patterns that previously caused catastrophic regular-expression backtracking
(repeated comment openers and repeated `<head` prefixes), the work performed
MUST grow proportionally to the body size, so that processing a body of a given
size stays within the same order of magnitude as processing a benign body of
the same size.

#### Scenario: Comment-shaped body

- **WHEN** an HTML response body consists of a long repetition of comment
  openers followed by a closing comment, and `open_in_browser` is called
- **THEN** the call completes with the base tag injected and the body written
  unmodified apart from that injection, without spending time proportional to
  the square of the body length

#### Scenario: Head-shaped body

- **WHEN** an HTML response body consists of a long repetition of `<head`
  prefixes that never terminate the tag, and `open_in_browser` is called
- **THEN** the call completes and the base tag is injected at the start of the
  body, without spending time proportional to the square of the body length

### Requirement: Effective adversarial inputs

Each adversarial input used to guard this behaviour MUST be an input that
actually triggers super-linear behaviour in the historical vulnerable pattern
it documents. An input whose processing time is indistinguishable between the
vulnerable and the safe pattern MUST NOT be used as an exploit input.

#### Scenario: Documented pattern is exercised

- **WHEN** a regression test declares that an input is an exploit for a
  historical pattern
- **THEN** the test demonstrates, within its own runtime, that the historical
  pattern scales super-linearly on that input compared with the current
  implementation

### Requirement: Deterministic regression verification

The regression tests for this capability MUST reach a pass/fail decision that
does not depend on the absolute speed of the machine or Python interpreter
running the suite.

#### Scenario: Slow or loaded machine

- **WHEN** the regression tests run on a machine that is slower or more loaded
  than the machine the budget was tuned on
- **THEN** a correct implementation still passes, and a regression that
  reintroduces catastrophic backtracking still fails

### Requirement: Preserved open_in_browser behaviour

Reworking the adversarial-input tests MUST NOT reduce the existing behavioural
coverage of `open_in_browser`.

#### Scenario: Existing behavioural tests still run

- **WHEN** the test suite for `open_in_browser` is executed
- **THEN** base-tag injection after a doctype, preservation of HTML comments,
  base-URL preservation, the `.txt` extension for text responses, and the
  `TypeError` for unsupported response types are still verified
