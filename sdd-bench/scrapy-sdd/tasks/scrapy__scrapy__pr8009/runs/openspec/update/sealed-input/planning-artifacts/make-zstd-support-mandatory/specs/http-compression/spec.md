## Purpose

Defines how Scrapy's HTTP compression downloader middleware negotiates and
decodes compressed response bodies, so that servers and downstream code can
rely on a stable set of supported content encodings.

## ADDED Requirements

### Requirement: Zstandard decompression is always available

The downloader middleware SHALL be able to decode `zstd`-encoded response
bodies in every supported installation, without the user installing an
optional package. A `zstd`-encoded response body SHALL be decompressed into the
original payload and the `Content-Encoding` header SHALL be removed from the
resulting response once decoding succeeds.

#### Scenario: Static zstd body with declared content size

- **WHEN** a response declares `Content-Encoding: zstd` and carries a zstd
  frame that records its decompressed size
- **THEN** the middleware SHALL return a response whose body is the
  decompressed payload
- **AND** the resulting response SHALL no longer carry a `Content-Encoding`
  header

#### Scenario: Streaming zstd body without content size

- **WHEN** a response declares `Content-Encoding: zstd` and carries a zstd
  frame that does not record its decompressed size
- **THEN** the middleware SHALL return a response whose body is the
  decompressed payload, identical to the decoded output of an equivalent frame
  that does declare its size

### Requirement: Advertised encodings include zstd

The middleware SHALL include `zstd` in the `Accept-Encoding` request header it
sends, unconditionally, in addition to the other supported encodings
(`gzip`, `deflate`, and `br`). The advertised set SHALL NOT depend on which
optional dependencies happen to be importable.

#### Scenario: Default Accept-Encoding header

- **WHEN** the middleware processes a request that does not already define an
  `Accept-Encoding` header
- **THEN** it SHALL set `Accept-Encoding` to the comma-separated list of
  supported encodings, including `zstd`

#### Scenario: Existing Accept-Encoding header is preserved

- **WHEN** a request already defines an `Accept-Encoding` header
- **THEN** the middleware SHALL leave it unchanged

### Requirement: Decompressed size limits apply to zstd

The middleware SHALL enforce the configured maximum decompressed size
(`DOWNLOAD_MAXSIZE`, or the per-request/spider override) while decoding zstd
bodies, in the same way as for the other supported encodings, and it SHALL stop
decoding and report an error as soon as the limit is exceeded.

#### Scenario: zstd body exceeds the maximum decompressed size

- **WHEN** a `zstd`-encoded response would decompress to more bytes than the
  configured `DOWNLOAD_MAXSIZE`
- **THEN** the middleware SHALL ignore the response with an error stating the
  decompressed size exceeded the configured maximum

### Requirement: Exhausted zstd streams decode cleanly

The middleware SHALL detect the end of a zstd stream and SHALL NOT emit
decoded data past the end of the compressed input.

#### Scenario: Truncated zstd stream

- **WHEN** a `zstd`-encoded response body is truncated
- **THEN** the middleware SHALL return a response with an empty body instead of
  raising or emitting partial garbage

### Requirement: Unsupported encodings are reported

When a response declares a content encoding the middleware cannot decode, it
SHALL leave that encoding in place and log a warning naming the encoding. Once
zstd decoding is always available, the warning SHALL NOT claim that an extra
package is required for `zstd`.

#### Scenario: Unknown content encoding

- **WHEN** a response declares a content encoding the middleware does not
  support
- **THEN** the middleware SHALL keep the response body unchanged
- **AND** it SHALL log a warning that names the unsupported encoding
