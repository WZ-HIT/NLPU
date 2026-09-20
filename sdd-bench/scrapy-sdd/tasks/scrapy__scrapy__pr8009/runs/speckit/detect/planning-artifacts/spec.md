# Feature Specification: Mandatory zstd decompression

**Feature Branch**: `8009-mandatory-zstd`

**Created**: 2026-09-20

**Status**: Draft

**Input**: PR 8009, "Use compression.zstd/backports.zstd and make zstd support mandatory"

## User Scenarios & Testing

### User Story 1 - Decode zstd responses by default (Priority: P1)

Scrapy users receive zstd-compressed HTTP responses without installing an
optional compression dependency or enabling a feature extra.

**Why this priority**: A normal installation must be able to decode every
encoding Scrapy advertises in `Accept-Encoding`.

**Independent Test**: Construct the HTTP compression middleware for a default
crawler, process the existing static and streaming zstd fixtures, and confirm
the decoded body and response headers match the other supported encodings.

**Acceptance Scenarios**:

1. **Given** a default Scrapy installation, **When** a request is processed,
   **Then** `zstd` is included in `Accept-Encoding`.
2. **Given** a valid zstd response, **When** the middleware processes it,
   **Then** the body is decoded and `Content-Encoding` is removed.

---

### User Story 2 - Preserve decompression safety limits (Priority: P2)

Users retain existing download-size and warning limits for zstd responses.

**Why this priority**: Making zstd mandatory must not weaken protection against
compression bombs or change warning behavior.

**Independent Test**: Run the existing zstd compression-bomb and download-size
warning scenarios without dependency-based skips.

**Acceptance Scenarios**:

1. **Given** a zstd body whose decoded size exceeds `DOWNLOAD_MAXSIZE`,
   **When** the middleware processes it, **Then** the response is ignored.
2. **Given** a decoded zstd body above `DOWNLOAD_WARNSIZE`, **When** the
   middleware processes it, **Then** the standard warning is emitted.

---

### User Story 3 - Use the standard zstd API consistently (Priority: P3)

Scrapy uses the standard-library zstd module on supported Python versions and
the compatible backport elsewhere.

**Why this priority**: Users and packagers should not need the separate
`zstandard` package or its `zstd` extra.

**Independent Test**: Inspect the declared runtime dependency and import path,
then exercise the zstd fixtures on the active Python version.

**Acceptance Scenarios**:

1. **Given** Python 3.14 or newer, **When** zstd is imported, **Then** it comes
   from `compression.zstd`.
2. **Given** Python older than 3.14, **When** zstd is imported, **Then** it
   comes from `backports.zstd`, which is a mandatory runtime dependency.

### Edge Cases

- A zstd frame without an embedded content size.
- A streaming zstd frame without an embedded content size.
- A truncated zstd stream.
- A zstd compression bomb constrained by a request setting, spider attribute,
  or request metadata.
- Python versions on both sides of the `3.14` standard-library boundary.

## Requirements

### Functional Requirements

- **FR-001**: A default installation MUST be able to decode zstd responses.
- **FR-002**: `zstd` MUST always be advertised in `Accept-Encoding`.
- **FR-003**: zstd decoding MUST use `compression.zstd` on Python 3.14+.
- **FR-004**: zstd decoding MUST use `backports.zstd` on Python before 3.14.
- **FR-005**: `backports-zstd` MUST be a mandatory dependency for Python before
  3.14, not an optional extra.
- **FR-006**: The obsolete `zstandard` dependency, extra, and installation
  guidance MUST be removed.
- **FR-007**: Existing zstd size-limit, warning, truncation, and multi-encoding
  behavior MUST remain unchanged.

### Key Entities

- **Accepted encoding list**: The encodings advertised by the HTTP compression
  middleware.
- **Zstd decompressor**: The standard-library or backport decoder subject to
  the existing maximum-size checks.
- **Runtime dependency declaration**: The project metadata that guarantees the
  backport is installed where the standard-library module is unavailable.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of existing zstd decoding fixtures pass in an environment
  with only the declared runtime dependencies.
- **SC-002**: All zstd-specific tests run rather than being skipped when the
  optional `zstandard` package is absent.
- **SC-003**: No supported encoding is advertised without an available decoder.
- **SC-004**: Existing maximum-size and warning tests continue to pass for zstd.

## Assumptions

- The existing binary fixtures and expected decompressed output remain valid.
- Python 3.14 provides the `compression.zstd` module.
- `backports.zstd` provides the compatible API needed by Scrapy.
- This planning task does not modify project code or tests and does not run the
  test suite.
