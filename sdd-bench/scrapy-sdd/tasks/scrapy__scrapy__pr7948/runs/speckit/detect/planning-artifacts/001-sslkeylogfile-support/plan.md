# Implementation Plan: SSLKEYLOGFILE Support

**Branch**: `001-sslkeylogfile-support` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-sslkeylogfile-support/spec.md`

## Summary

Add opt-in TLS key logging for HTTPS downloads. A shared SSL utility should resolve the configured destination and produce standard NSS-format records for both Python `ssl.SSLContext` and pyOpenSSL `Context` instances. Existing handlers must remain unchanged when the destination is unset.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: stdlib `ssl`, pyOpenSSL, Twisted, optional HTTPX/HTTP2 support

**Storage**: User-selected append-only text file; no database

**Testing**: pytest with the repository's existing HTTPS mock servers and context-factory tests

**Target Platform**: Cross-platform Python where Scrapy's HTTPS handlers run

**Project Type**: Library / framework

**Performance Goals**: No measurable overhead when disabled; key logging performs only the file I/O required when explicitly enabled

**Constraints**: Disabled by default; no secrets in normal logs; preserve TLS settings and certificate verification behavior

**Scale/Scope**: The shared TLS layer plus built-in HTTPS download handlers and documentation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository constitution is an unpopulated template, so no project-specific gates are defined. The design still passes general gates: it is narrowly scoped, adds no mandatory dependency, remains independently testable, and makes the security-sensitive behavior explicit opt-in.

## Project Structure

### Documentation (this feature)

```text
specs/001-sslkeylogfile-support/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ssl-keylogfile.md
├── spec.md
└── tasks.md
```

### Source Code (repository root)

```text
scrapy/
├── utils/ssl.py
├── core/downloader/contextfactory.py
├── core/downloader/handlers/_httpx.py
├── core/downloader/handlers/http11.py
└── core/downloader/handlers/http2.py

docs/topics/
└── settings.rst

tests/
├── test_utils_ssl.py
├── test_core_downloader.py
├── test_downloader_handler_httpx.py
├── test_downloader_handler_twisted_http11.py
├── test_downloader_handler_twisted_http2.py
└── utils/bases/download_handlers_http.py
```

**Structure Decision**: Extend the existing SSL utility and context-factory layers so both stdlib and Twisted handlers share one key-logging policy. No new package or service is introduced.

## Complexity Tracking

No constitution violations or unjustified complexity.
