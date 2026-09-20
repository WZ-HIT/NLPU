# Design Document

## Overview

TLS key logging is a diagnostic feature enabled by the conventional `SSLKEYLOGFILE` environment variable. The design reuses the existing TLS context construction points so that no new setting is required and behavior is consistent across built-in handlers.

## Boundary Commitments

### This Spec Owns

- Reading `SSLKEYLOGFILE` at TLS-context creation time.
- Installing a pyOpenSSL key-log callback for Twisted-created contexts.
- Setting the stdlib `ssl.SSLContext` key-log filename for httpx-created contexts.
- Tests and documentation for this behavior.

### This Spec Does Not Own

- TLS verification, cipher, or protocol-version policy.
- Key logging for third-party download handlers.
- Rotation, locking, or cleanup of the key-log file.

## Architecture

Two context implementations must be covered:

| Client path | Context type | Integration point |
|---|---|---|
| Twisted HTTP/1.1 and HTTP/2 | `OpenSSL.SSL.Context` created by `_ScrapyCertificateOptions` | `scrapy/core/downloader/contextfactory.py` |
| httpx | `ssl.SSLContext` created by `_make_ssl_context()` | `scrapy/utils/ssl.py` |

The implementation should centralize environment lookup and pyOpenSSL callback installation in `scrapy/utils/ssl.py`, then invoke that helper from `_ScrapyCertificateOptions._makeContext()` before the context is used. The stdlib path should set `keylog_filename` while constructing the context.

## Key Decisions

- Support the standard environment variable rather than adding a Scrapy setting; this matches Python, curl, and browser behavior and keeps configuration out of crawler settings.
- Fail loudly on an unwritable path; silently ignoring the request would produce misleading diagnostics.
- Install the pyOpenSSL callback immediately after context creation because pyOpenSSL forbids changing key-log callbacks after the context is used.

## Risks and Mitigations

- A shared callback must keep its file handle alive for the lifetime of the context; retain it on the context/helper closure.
- Concurrent connections may write to one file; append-only NSS-format lines keep records parseable.
- Custom context factories may bypass these paths; document the limitation rather than wrapping arbitrary third-party factories.
