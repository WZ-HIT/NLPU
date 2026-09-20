# Detection Notes

Phase: `detect`. Scope: locate the repository test files that would have to change
for pull request scrapy/scrapy#8009 ("Use compression.zstd/backports.zstd and make
zstd support mandatory"). No test run, no code or test edit.

## Production surface touched by the change

| Module | Current zstd-relevant code |
| --- | --- |
| `scrapy/utils/_compression.py` | `with contextlib.suppress(ImportError): import zstandard`; `_unzstd()` uses `zstandard.ZstdDecompressor()` |
| `scrapy/downloadermiddlewares/httpcompression.py` | `from importlib.util import find_spec`; `ACCEPTED_ENCODINGS` gets `b"zstd"` only `if find_spec("zstandard") is not None`; `_warn_unknown_encoding()` appends "You need to install zstandard to decode 'zstd'." |
| `pyproject.toml` | optional extra `zstd = ["zstandard>=0.16.0; implementation_name != 'pypy'"]` |
| `tox.ini` | `zstandard==0.25.0`, the `extra-deps` line and `zstandard==0.16.0` in `min-extra-deps` |
| `docs/topics/downloader-middleware.rst`, `docs/topics/optimize.rst`, `docs/intro/install.rst`, `docs/news.rst` | zstd extra / `zstandard` package references |

## Evidence collected

1. `grep -ril "zstd\|zstandard"` over the repository returns only:
   `docs/intro/install.rst`, `docs/news.rst`, `docs/topics/downloader-middleware.rst`,
   `docs/topics/optimize.rst`, `pyproject.toml`,
   `scrapy/downloadermiddlewares/httpcompression.py`, `scrapy/utils/_compression.py`,
   `tests/test_downloadermiddleware_httpcompression.py`, `tox.ini`.
   Only one of the hits is under `tests/`.
2. `grep -rn "zstandard\|zstd" tests/` yields hits in a single file:
   `tests/test_downloadermiddleware_httpcompression.py`.
3. `grep -rn "importorskip" tests/` shows the only zstd gate in the suite,
   `pytest.importorskip("zstandard")` inside `_skip_if_no_zstd()` in that same file.
4. `grep -rn "ACCEPTED_ENCODINGS\|_unzstd\|_compression" tests/` matches only that
   same file, which imports `_CHUNK_SIZE` and `_DecompressionMaxSizeExceeded` from
   `scrapy.utils._compression` and asserts `Accept-Encoding` against
   `ACCEPTED_ENCODINGS`.
5. Other `Content-Encoding` / `Accept-Encoding` assertions elsewhere in the suite
   (`tests/test_downloader_handlers.py`, `tests/utils/bases/http_request.py`,
   `tests/utils/bases/download_handlers_http.py`) are gzip/curl/httpx specific and
   never involve zstd, so they are not candidates.
6. The runtime image provides `backports_zstd-1.7.0` and does not provide
   `zstandard`, consistent with the post-change environment in which the
   `importorskip("zstandard")` guards above can no longer protect the zstd tests.

## Candidate

- `tests/test_downloadermiddleware_httpcompression.py` — sole test module covering
  the two production modules that the change rewrites. See
  `../detection-draft.json` for the symbol list and the per-candidate reason.

## Excluded

- `tests/test_dependencies.py` — parses `tox.ini`, but only to pin the Twisted
  version for the `min` environment; it contains no zstd assertion.
- `tests/mockserver/http_resources.py` — test support code; its only compression
  branch is gzip.
- `tests/test_downloader_handlers.py` and the `tests/utils/bases/*` helpers —
  gzip-only encoding assertions.
- `tests/test_utils_gz.py` — covers `scrapy.utils.gz` (gzip), not zstd.
