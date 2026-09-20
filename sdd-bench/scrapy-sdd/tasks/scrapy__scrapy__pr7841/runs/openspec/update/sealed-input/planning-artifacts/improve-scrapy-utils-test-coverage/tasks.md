## 1. Regression tests for changed helpers

- [ ] 1.1 Add a regression test for `_inflate()` with a raw-deflate body followed by extra bytes and a max-size assertion; verify it fails (hangs or errors) before the fix and passes after it in `tests/test_downloadermiddleware_httpcompression.py`
- [ ] 1.2 Extend `tests/test_utils_python.py` so `get_func_args()`/`get_func_args_dict()` are asserted with `functools.partial` positional and keyword arguments; verify the new assertions fail before the fix
- [ ] 1.3 Add coverage for `scrapy.utils.deprecate.argument_is_required()` with partials in `tests/test_utils_deprecate.py` and verify it passes
- [ ] 1.4 Add SSL-focused tests for the deprecated helpers (`ffi_buf_to_string()`, `x509name_to_string()`, `get_temp_key_info()`) and `get_openssl_version()`, and verify they pass
- [ ] 1.5 Update the pyOpenSSL-conditional assertions (`tests/utils/bases/download_handlers_http.py`, `tests/mockserver/utils.py`, `tests/test_core_downloader.py`) for the new floor and verify the affected test modules pass

## 2. Helper fixes

- [ ] 2.1 Fix `_inflate()` in `scrapy/utils/_compression.py` so decoding stops when a decompression step makes no progress; verify task 1.1 passes
- [ ] 2.2 Fix `get_func_args_dict()` in `scrapy/utils/python.py` to account for partial positional and keyword arguments; verify task 1.2 passes
- [ ] 2.3 Fix `ffi_buf_to_string()` in `scrapy/utils/ssl.py` to return `_ffi_buf_to_string()`; verify task 1.4 passes

## 3. Dependency floor and coverage

- [ ] 3.1 Require `pyOpenSSL >= 24.3.0` with compatible `cryptography`/`service_identity` minimums in `pyproject.toml` and remove the now-unreachable version branches and `# pragma: no cover` markers; verify the SSL-related test modules still pass
- [ ] 3.2 Enable coverage in the `pypy3` tox environment and verify a pypy3 run reports coverage for `scrapy/utils`

## 4. Verification

- [ ] 4.1 Run the affected test modules (`tests/test_utils_python.py`, `tests/test_utils_deprecate.py`, `tests/test_downloadermiddleware_httpcompression.py`, `tests/test_core_downloader.py`, newer SSL tests) and confirm they pass
- [ ] 4.2 Confirm the OpenSpec change validates with `openspec validate improve-scrapy-utils-test-coverage`
