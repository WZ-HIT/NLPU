## Why

The ReDoS regression tests for `scrapy.utils.response.open_in_browser` are
unreliable: `_assert_open_in_browser_is_fast()` decides pass/fail by comparing
`process_time()` against a fixed 0.2 s budget, so the result depends on the
machine and interpreter speed rather than on the property being guarded. In
addition, the adversarial input used by the comment case is documented as an
exploit for the old comment-removal pattern `/<!--.*?-->/`, but the current
implementation no longer evaluates any comment-removal pattern, so that input
cannot fail if such a pattern is reintroduced. The guard therefore both flakes
and gives weaker protection than it claims.

## What Changes

- Rework the adversarial-input regression tests in `tests/test_utils_response.py`
  so the pass/fail decision no longer rests on an absolute CPU-time budget
  measured on the machine running the suite.
- Correct the adversarial inputs so each one is provably an exploit for the
  historical pattern it documents (super-linear behaviour on the old pattern,
  linear behaviour on the current implementation), instead of an input that no
  current code path can distinguish.
- Keep the existing behavioural coverage of `open_in_browser` intact: base-tag
  injection relative to a doctype, comment handling, base-URL preservation,
  text responses, and the unsupported-response-type `TypeError`.
- No public API, signature, or user-visible behaviour of `open_in_browser`
  changes; this is a test-quality change only.

## Capabilities

### New Capabilities

- `open-in-browser-redos-guard`: the responsiveness guarantee for
  `open_in_browser` on adversarial HTML bodies, and the deterministic,
  self-validating way that guarantee is regression-tested.

### Modified Capabilities

<!-- No existing specs exist under openspec/specs/, so nothing is modified. -->

## Impact

- `tests/test_utils_response.py`: the ReDoS tests and their shared helper are
  rewritten; the remaining `open_in_browser` tests keep their assertions.
- No changes to `scrapy/utils/response.py` interfaces, to public behaviour, or
  to any dependency. Test runtime for the suite may change because the
  adversarial inputs are re-sized.
