# Requirements Document

## Introduction

Scrapy should honor the standard `SSLKEYLOGFILE` environment variable so users can capture TLS key material for debugging HTTPS traffic with tools such as Wireshark. The behavior must apply to every built-in HTTPS download path without changing existing TLS verification, version, or cipher settings.

## Boundary Context

- **In scope**: reading `SSLKEYLOGFILE` when an HTTPS client TLS context is created; writing OpenSSL/NSS-format key material for Twisted HTTP/1.1, Twisted HTTP/2, and the httpx download handler.
- **Out of scope**: changing certificate verification defaults, adding a new Scrapy setting, capturing server-side TLS keys, and third-party handlers that create their own contexts.
- **Adjacent expectations**: existing `DOWNLOAD_TLS_MIN_VERSION`, `DOWNLOAD_TLS_MAX_VERSION`, `DOWNLOADER_CLIENT_TLS_CIPHERS`, and `DOWNLOAD_VERIFY_CERTIFICATES` behavior remains unchanged.

## Requirements

### Requirement 1: Standard environment variable support

**Objective:** As a Scrapy user debugging TLS, I want HTTPS clients to honor `SSLKEYLOGFILE`, so that packet captures can be decrypted without application changes.

#### Acceptance Criteria

1. When `SSLKEYLOGFILE` is unset, the HTTPS client shall not enable TLS key logging.
2. When `SSLKEYLOGFILE` is set to a writable path, the HTTPS client shall write OpenSSL/NSS-format key material to that path during TLS handshakes.
3. When `SSLKEYLOGFILE` is set but the path cannot be opened, the TLS connection setup shall fail with the underlying filesystem error rather than silently disabling key logging.
4. The key-logging behavior shall be documented as an environment-variable feature, not as a Scrapy setting.

### Requirement 2: Built-in HTTPS handler coverage

**Objective:** As a Scrapy user, I want consistent key logging regardless of the built-in download handler, so that diagnostics do not depend on handler choice.

#### Acceptance Criteria

1. The Twisted HTTP/1.1 HTTPS handler shall install key logging on each client TLS context it creates.
2. The Twisted HTTP/2 handler shall install key logging through the same shared context-factory path.
3. The httpx download handler shall pass the configured key-log path to the standard-library `ssl.SSLContext` it creates.
4. Handler-specific TLS tests shall continue to pass when `SSLKEYLOGFILE` is unset.
