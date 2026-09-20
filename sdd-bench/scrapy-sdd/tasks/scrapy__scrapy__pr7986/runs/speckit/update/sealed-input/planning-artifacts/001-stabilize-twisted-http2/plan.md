# Implementation Plan: Stabilize and Privatize the Twisted HTTP/2 Handler

**Branch**: `001-stabilize-twisted-http2` | **Date**: 2026-09-20 | **Spec**: `specs/001-stabilize-twisted-http2/spec.md`

**Input**: Feature specification from `specs/001-stabilize-twisted-http2/spec.md`

## Summary

Promote the Twisted-based HTTP/2 download handler from experimental status to a supported built-in handler, while making its implementation-only classes private. Keep the documented `H2DownloadHandler` entry point and `DOWNLOAD_HANDLERS` configuration stable, update internal references and tests to private names, and leave the HTTPX handler's experimental status unchanged.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: Twisted, `h2`, Scrapy download-handler framework

**Storage**: N/A

**Testing**: pytest with pytest-twisted; do not execute tests during Detect planning

**Target Platform**: Cross-platform Python environments with a Twisted reactor

**Project Type**: Library/framework

**Performance Goals**: Preserve existing HTTP/2 connection reuse, concurrency, timeout, and response behavior

**Constraints**: No supported configuration change; no public-facing migration requirement; internal class renames must be consistent

**Scale/Scope**: HTTP/2 download handler, `scrapy/core/http2` implementation package, documentation, and directly related tests

## Constitution Check

The repository constitution is a template without project-specific gates. No violation identified: the change preserves documented user behavior, limits internal API exposure, and requires verification through existing tests.

## Project Structure

### Documentation (this feature)

```text
specs/001-stabilize-twisted-http2/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
scrapy/
├── core/
│   ├── downloader/
│   │   └── handlers/
│   │       └── http2.py
│   └── http2/
│       ├── agent.py
│       ├── protocol.py
│       └── stream.py
docs/
└── topics/
    └── download-handlers.rst
tests/
├── test_downloader_handler_twisted_http2.py
└── test_http2_client_protocol.py
```

**Structure Decision**: Keep the existing handler module and HTTP/2 implementation package. Privatize implementation symbols in place so the documented handler path remains stable.

## Complexity Tracking

No constitution violations or added architectural complexity.
