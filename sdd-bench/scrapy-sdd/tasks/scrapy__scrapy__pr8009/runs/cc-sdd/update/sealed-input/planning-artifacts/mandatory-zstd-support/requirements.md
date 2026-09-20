# Requirements Document

## Project Description (Input)

Scrapy users who need zstd-compressed HTTP response decoding have to install the
third-party `zstandard` package through the optional `zstd` extra. This makes zstd
support conditional: the `Accept-Encoding` header only advertises `zstd` when
`zstandard` happens to be importable, and responses that arrive with
`Content-Encoding: zstd` are left undecoded with a warning telling the user to
install `zstandard`. Python 3.14 ships `compression.zstd` in the standard library
(PEP 784), and the `backports.zstd` package provides the same API for older
interpreters, so the optional dependency is no longer needed: zstd decompression
should become a mandatory capability implemented against the stdlib module or its
backport (see pull request scrapy/scrapy#8009, which resolves issue #6978 and
closes #7083, on base commit 3c6a62db47536df89676ab9d7347acf5c5c8a2e4).

## Requirements

### Requirement 1: Mandatory zstd decoding

**User story:** As a Scrapy user, I want zstd response decompression to work out of
the box, so that I do not need to discover and install an optional extra to read
zstd-compressed responses.

#### Acceptance Criteria

1. WHEN `HttpCompressionMiddleware` is enabled THEN `ACCEPTED_ENCODINGS` SHALL
   contain `b"zstd"` unconditionally.
2. WHEN a request passes through `HttpCompressionMiddleware.process_request` THEN
   the `Accept-Encoding` header SHALL advertise `zstd` together with `gzip`,
   `deflate` and `br`.
3. WHEN a response carries `Content-Encoding: zstd` THEN
   `HttpCompressionMiddleware` SHALL decode it without checking for an optional
   third-party package at import time.
4. WHEN a `zstd` response is decoded THEN the decoding SHALL respect the same
   `DOWNLOAD_MAXSIZE` / `DOWNLOAD_WARNSIZE` limits and stats accounting as the
   other supported encodings.

### Requirement 2: Backend selection

**User story:** As a Scrapy maintainer, I want the zstd code path to use
`compression.zstd` where available, so that Scrapy relies on the standard library
and the project can track upstream.

#### Acceptance Criteria

1. WHEN Scrapy runs on an interpreter that provides the stdlib `compression.zstd`
   module THEN the zstd decompressor SHALL be built from `compression.zstd`.
2. WHEN the stdlib module is unavailable THEN the zstd decompressor SHALL be
   built from the `backports.zstd` backport instead.
3. WHERE a package dependency is declared, `backports.zstd` SHALL be required
   only for interpreter versions that lack `compression.zstd`.

### Requirement 3: Removal of optional-extra behaviour

**User story:** As a Scrapy user, I want the documentation and runtime warnings to
match reality, so that I am not told to install a package that is no longer used.

#### Acceptance Criteria

1. WHEN a response uses an encoding that Scrapy cannot decode THEN the warning
   SHALL NOT instruct the user to install `zstandard`.
2. WHEN the installation extras are documented THEN the `zstd` extra SHALL no
   longer be presented as required for zstd decompression.

## Out of Scope

- Test execution, dependency installation and any change to production code or
  test code. This run covers only the specification and detection planning
  phases of the cc-sdd workflow.
