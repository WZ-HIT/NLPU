## Why

Several helpers in `scrapy.utils` are only partially covered by tests, which hid three defects: `_inflate()` can spin forever on a raw-deflate body followed by extra bytes, `ffi_buf_to_string()` calls itself instead of its private implementation, and `get_func_args_dict()` compares parameter *names* against a `functools.partial`'s positional *values*. The same work can drop the pyOpenSSL < 24.3.0 compatibility branches, removing many uncovered lines.

## What Changes

- Add regression tests for `scrapy.utils._compression._inflate()` covering a deflate payload followed by extra bytes (must terminate and decode) and the max-size guard.
- Add regression tests for `scrapy.utils.python.get_func_args_dict()` / `get_func_args()` with `functools.partial` positional and keyword arguments (exact signature preferred; the CPython < 3.13 fallback stays accepted).
- Fix `ffi_buf_to_string()` so it returns the deprecated wrapper's value instead of recursing, and cover the deprecated `scrapy.utils.ssl` helpers.
- **BREAKING**: require `pyOpenSSL >= 24.3.0` (and with it `cryptography >= 41.0.5` and `service_identity >= 24.2.0`), removing the version conditionals and their `# pragma: no cover` markers.
- Make the `pypy3` tox environment measure coverage so PyPy-specific branches in `scrapy.utils` are visible.

## Capabilities

### New Capabilities

- `utils-integrity`: observable guarantees of the shared `scrapy.utils` helpers used across the downloader, middleware and deprecation machinery: decompression must terminate, callable introspection must report the real remaining arguments, and deprecated SSL helpers must delegate correctly.

### Modified Capabilities

None.

## Impact

- Production code: `scrapy/utils/_compression.py`, `scrapy/utils/python.py`, `scrapy/utils/ssl.py`, `scrapy/utils/_deps_compat.py`, and the callers that rely on them (`scrapy/downloadermiddlewares/httpcompression.py`, `scrapy/utils/deprecate.py`, `scrapy/core/downloader/*`, `scrapy/utils/versions.py`).
- Tests and test helpers: `tests/test_utils_python.py`, `tests/test_utils_deprecate.py`, `tests/test_downloadermiddleware_httpcompression.py`, `tests/test_utils_ssl.py` (new), `tests/test_core_downloader.py`, `tests/utils/bases/download_handlers_http.py`, `tests/mockserver/utils.py`.
- Packaging: minimum dependency versions in `pyproject.toml` and the pypy3 environment in `tox.ini`. No public API is added; only a targeted bug fix on `ffi_buf_to_string()`, which was unusable (infinite recursion).
