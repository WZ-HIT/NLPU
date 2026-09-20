## Why

Zstandard (`zstd`) response decompression is currently a best-effort feature: it
only works when the third-party `zstandard` distribution happens to be
installed, and the downloader middleware silently degrades otherwise. Zstd is
now widely served by real sites, Python 3.14 ships a standard-library
implementation (`compression.zstd`), and a maintained backport
(`backports.zstd`) covers older interpreters, so support can be guaranteed for
every installation instead of being optional.

## What Changes

- Always provide zstd decompression: import `compression.zstd` on interpreters
  that ship it and fall back to `backports.zstd` elsewhere.
- **BREAKING** Make the zstd backend a default installation requirement
  (`backports.zstd>=1.3.0; python_version < "3.14"`, since Python 3.14+ provides
  `compression.zstd`) instead of an optional extra, and drop the now-redundant
  `zstd` extra and the `zstandard` dependency from packaging/tox configuration.
- Always advertise `zstd` in the `Accept-Encoding` request header sent by the
  HTTP compression downloader middleware (the middleware no longer inspects the
  environment to decide).
- Remove the now-impossible "you need to install zstandard" warning path for
  undecodable zstd responses; unsupported-encoding reporting keeps working for
  any genuinely unknown encoding.
- Update documentation that currently describes zstd as opt-in/optional.

## Capabilities

### New Capabilities

- `http-compression`: behavior of the HTTP compression downloader middleware -
  which content encodings it advertises to servers, which response encodings it
  decodes, and how it reports encodings it cannot handle.

### Modified Capabilities

<!-- None: `openspec/specs/` is empty at this commit, so there are no existing
     capabilities whose requirements change. -->

## Impact

- Code: `scrapy/utils/_compression.py` (zstd backend import and `_unzstd`),
  `scrapy/downloadermiddlewares/httpcompression.py` (`ACCEPTED_ENCODINGS`,
  unsupported-encoding warning), `scrapy/utils/_compression.py` imports.
- Packaging/dependencies: `pyproject.toml` (required dependencies, removal of
  the `zstd` extra), `tox.ini` (base/extra/min/vcs dependency lists).
- Docs: `docs/intro/install.rst`, `docs/topics/optimize.rst`,
  `docs/topics/downloader-middleware.rst`, `docs/news.rst`.
- Tests: `tests/test_downloadermiddleware_httpcompression.py` (zstd skip guards
  and the "zstd unsupported" expectations).
- Compatibility: installs gain a mandatory dependency; environments previously
  relying on zstd being absent (including any test asserting
  "unsupported zstd") change behavior. Python/PyPy support for the backport
  must be confirmed as part of implementation.
