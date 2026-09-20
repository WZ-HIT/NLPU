# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7841`

Base commit: `95c16aa9af7c51f26ba3ea8512b4ba782f5d216f`

## Title

Improve the test coverage of scrapy.utils

## Body

Includes:

-   A bug fix on `_inflate()`, it could loop forever on a deflate body followed by any extra bytes.
-   `ffi_buf_to_string()` called itself instead of `_ffi_buf_to_string()`, now fixed.
-   `get_func_args_dict()` compared parameter *names* against a partial's positional
    *values*, so `get_func_args(partial(f, "b"))` returned `[]` instead of `["b"]`, now fixed.
-   Require `pyOpenSSL >= 24.3.0`, and with it `cryptography >= 41.0.5` and
    `service_identity >= 24.2.0`. It allowed to simplify the code and avoid many "no cover" lines.
-   The `pypy3` tox env now measures coverage, for some PyPy-specific branches.
