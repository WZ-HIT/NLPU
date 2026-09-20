## 1. Dependency declaration

- [ ] 1.1 Add `backports.zstd>=1.3.0; python_version < "3.14"` to `[project]
  dependencies` in `pyproject.toml` and remove the `zstd` entry from
  `[project.optional-dependencies]`; verify with a build/metadata check (e.g.
  `python -m build --sdist` metadata or `pip install --dry-run .`) that the
  required dependency and no `zstd` extra remain.
- [ ] 1.2 Confirm the `backports.zstd>=1.3.0` floor is sufficient for the
  `ZstdDecompressor` streaming API used by `_unzstd()` and keep the same floor
  in `tox.ini` `min-extra-deps`; verify that minimum-version environment still
  resolves and runs the zstd tests.

## 2. Zstd backend import

- [ ] 2.1 In `scrapy/utils/_compression.py`, replace the
  `contextlib.suppress(ImportError)` + `import zstandard` block with a
  `compression.zstd` import that falls back to `backports.zstd`; verify by
  importing `scrapy.utils._compression` with the primary module unavailable
  and available.
- [ ] 2.2 Confirm the chosen backend exposes the streaming reader used by
  `_unzstd()` and adapt the function if it does not; verify a zstd frame with a
  recorded content size and a streaming frame without one both decode to the
  same payload.
- [ ] 2.3 Confirm `_unzstd()` still enforces `max_size` in `_CHUNK_SIZE` steps
  against the new backend; verify a decompression-bomb sample raises the
  size-exceeded error with the same reported "decompressed so far" bound as
  before.

## 3. Middleware behavior

- [ ] 3.1 In `scrapy/downloadermiddlewares/httpcompression.py`, make
  `ACCEPTED_ENCODINGS` unconditionally include `b"zstd"` and remove the
  `importlib.util.find_spec` probe (and its now-unused import); verify the
  `Accept-Encoding` header set by the middleware lists gzip, deflate, br and
  zstd.
- [ ] 3.2 Remove the `" You need to install zstandard to decode 'zstd'."`
  suffix from the unsupported-encoding warning while keeping the generic
  message for unknown encodings; verify a response with an unknown encoding
  still logs the encoding name and keeps its body unchanged.

## 4. Packaging, tox and docs

- [ ] 4.1 Remove the `zstandard` entries from `tox.ini` (`extra-deps`,
  `min-extra-deps`, `vcs-deps`) and let the new default dependency satisfy the
  zstd tests; verify the extra-deps and min-extra-deps environments resolve.
- [ ] 4.2 Update `docs/intro/install.rst`, `docs/topics/optimize.rst`,
  `docs/topics/downloader-middleware.rst` and add a `docs/news.rst` entry so
  zstd is documented as built in; verify no documentation still describes
  installing `zstandard` for zstd support.

## 5. Tests

- [ ] 5.1 Remove the `_skip_if_no_zstd()` helper and its call sites in
  `tests/test_downloadermiddleware_httpcompression.py`; verify the zstd tests
  run (not skip) in an environment without `zstandard` installed.
- [ ] 5.2 Remove `test_process_response_zstd_unsupported` (it asserts behavior
  that can no longer occur) and add or keep equivalent coverage for an
  encoding that is genuinely unknown; verify the new case asserts the
  unchanged-body plus warning behavior.
- [ ] 5.3 Verify the whole compression test module passes with only the new
  backend installed, including `test_process_request`, the zstd decompression
  tests, the compression-bomb tests, the warn-size tests and the truncated
  stream test.

## 6. Repository-wide verification

- [ ] 6.1 Run the project's lint/type checks (`pre-commit` / `mypy`) over the
  touched files; verify no unused imports remain, especially around the
  removed `find_spec` probe.
- [ ] 6.2 Run the targeted test suite (`pytest
  tests/test_downloadermiddleware_httpcompression.py`) plus a broader smoke run
  in the base tox environment; verify no dependency-resolution or import
  failures appear.
