## Purpose

Guarantee that the shared `scrapy.utils` helpers used by the downloader, the HTTP compression middleware and the deprecation machinery behave correctly on edge-case inputs and across supported dependency versions.

## ADDED Requirements

### Requirement: Deflate decoding must always terminate

The decompression helpers SHALL terminate for any input, including a raw-deflate stream followed by trailing bytes, and SHALL return only the decompressed payload.

#### Scenario: Raw deflate body with trailing bytes

- **WHEN** a raw-deflate body followed by extra bytes is decoded
- **THEN** decoding terminates, returns the decompressed payload, and does not raise an unhandled decompression error

#### Scenario: Decompressed size limit exceeded

- **WHEN** the decompressed output exceeds the configured maximum size
- **THEN** the helper raises the decompression limit error instead of returning the payload

### Requirement: Callable introspection ignores bound partial arguments

Callable argument introspection SHALL report the arguments that remain unbound after `functools.partial` arguments, both positional and keyword, have been applied.

#### Scenario: Partial with a positional argument

- **WHEN** `get_func_args()` is called on a callable partially applied with a positional value
- **THEN** the returned argument names exclude exactly the parameters bound by that value

#### Scenario: Deprecated class helper with a partial

- **WHEN** deprecation helpers that inspect an argument's presence receive a partially applied callable
- **THEN** the presence/absence answer matches the callable's real signature after partial application

### Requirement: Deprecated SSL helpers delegate to their implementation

Deprecated helpers in `scrapy.utils.ssl` SHALL return the value produced by their private implementation and warn once, instead of failing or recursing.

#### Scenario: Calling a deprecated SSL helper

- **WHEN** a deprecated SSL helper such as `ffi_buf_to_string()` is called
- **THEN** it emits a deprecation warning and returns the converted value from the private implementation

### Requirement: Supported pyOpenSSL floor

Scrapy SHALL require pyOpenSSL 24.3.0 or newer, together with compatible cryptography and service_identity releases, and MUST NOT carry code paths dedicated to older pyOpenSSL versions.

#### Scenario: Reading the OpenSSL version

- **WHEN** the SSL version string or certificate information is reported
- **THEN** the modern pyOpenSSL/cryptography APIs are used without version-conditional fallbacks
