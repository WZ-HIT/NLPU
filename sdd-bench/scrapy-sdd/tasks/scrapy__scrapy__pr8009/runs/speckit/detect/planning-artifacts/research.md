# Research: Mandatory zstd decompression

## Decision: Select the zstd module by Python version

Use `compression.zstd` on Python 3.14+ and `backports.zstd` on older supported
Python versions.

**Rationale**: The standard module is available on newer interpreters, while
the backport provides the same API for Python 3.10 through 3.13.

**Alternatives considered**: Keeping `zstandard`; retaining an optional extra;
requiring only the backport on every version. Each delays migration or adds a
redundant dependency on Python 3.14+.

## Decision: Make the backport a mandatory runtime dependency

Declare `backports-zstd>=1.3.0` for Python before 3.14 in the core project
dependencies and remove the `zstd` extra.

**Rationale**: Scrapy advertises zstd support by default, so its decoder must
be installed by default.

**Alternatives considered**: Leaving zstd optional while advertising it;
silently omitting it from `Accept-Encoding`; requiring users to opt in. These
create inconsistent capability negotiation.

## Decision: Add zstd unconditionally to accepted encodings

Initialize the middleware encoding list with `gzip`, `deflate`, `br`, and
`zstd`, and remove the unsupported-dependency warning path.

**Rationale**: Dependency availability is guaranteed, so runtime feature
detection and an installation hint are obsolete.

**Alternatives considered**: Keeping `find_spec()` detection; retaining the
warning for hypothetical missing installations. Both contradict the mandatory
support contract.

## Decision: Preserve bounded streaming semantics

Adapt the zstd decoder to the selected module's `ZstdDecompressor` API while
reading in `_CHUNK_SIZE` increments and checking `_check_max_size()` after each
chunk.

**Rationale**: Existing tests require exact maximum-size behavior, support for
frames without embedded content size, streaming frames, and truncated input.

**Alternatives considered**: One-shot decompression without incremental size
checks. That risks excessive allocation before a limit violation is detected.
