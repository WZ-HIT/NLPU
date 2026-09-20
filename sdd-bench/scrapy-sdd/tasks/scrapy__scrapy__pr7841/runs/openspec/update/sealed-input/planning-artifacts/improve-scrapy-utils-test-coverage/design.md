## Context

`scrapy.utils` holds shared helpers with thin test coverage. Three defects are currently reachable through existing behaviour: `_inflate()` loops forever when a raw-deflate stream is followed by extra bytes, `ffi_buf_to_string()` recurses into itself, and `get_func_args_dict()` skips parameters whose *names* appear among a partial's positional *values*. Raising the pyOpenSSL floor to 24.3.0 removes the X.509 compatibility branches that carried `# pragma: no cover` markers.

## Goals / Non-Goals

- Goals: fix the three defects, add regression coverage for the affected helpers, and simplify the pyOpenSSL version handling so coverage reflects real code.
- Non-Goals: no new public API, no behaviour change for valid inputs, no dependency bump beyond the pyOpenSSL chain, and no refactor of unrelated `scrapy.utils` modules.

## Decisions

- Keep the fixes local to the helper functions and test them where each helper is exercised today: `tests/test_utils_python.py` for introspection, `tests/test_utils_deprecate.py` for the deprecation caller, `tests/test_downloadermiddleware_httpcompression.py` (plus a direct unit test of `_inflate`) for decompression, and an SSL-focused module for the deprecated helpers and version reporting.
- For `_inflate()`, detect lack of progress (empty output with a non-emptied unconsumed tail) instead of trusting `decompressor.unconsumed_tail` to shrink, and keep the max-size checks on every produced chunk.
- For `get_func_args_dict()`, drop parameters positionally bound by `partial.args` and by name for `partial.keywords`, rather than testing membership of parameter names in the positional value tuple.
- For the pyOpenSSL floor, remove `PYOPENSSL_X509_DEPRECATED` together with the conditional branches in `scrapy/utils/ssl.py` and the test helpers that branch on it, and update the minimum versions in `pyproject.toml`.
- Enable coverage in the `pypy3` tox environment so PyPy-specific branches (`garbage_collect()`, weakref-based helpers) are reported.

## Risks / Trade-offs

- Removing the old pyOpenSSL path is a breaking dependency change for users on pyOpenSSL < 24.3.0; it is documented as such in the proposal.
- A direct `_inflate()` unit test depends on `zlib` behaviour rather than the middleware; the middleware-level deflate tests remain as integration coverage.

## Migration Plan

Update `pyproject.toml` minimums (`pyOpenSSL >= 24.3.0`, `cryptography >= 41.0.5`, `service_identity >= 24.2.0`), drop the version-conditional code, then land the regression tests in the same change.

## Open Questions

None.
