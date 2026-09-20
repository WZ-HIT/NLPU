# Requirements Document

## Introduction

Pull request `scrapy/scrapy#7986` ("Stop marking the Twisted-based HTTP/2
download handler as experimental, and privatize its API") closes issue
`scrapy/scrapy#5047`. The Twisted-based HTTP/2 download handler
(`scrapy.core.downloader.handlers.http2.H2DownloadHandler`) has been shipping
long enough that its experimental warning is no longer accurate, while the
supporting HTTP/2 client package (`scrapy.core.http2`) and handler API surface
still expose internals that Scrapy does not intend to support. This spec covers
only the detect-stage planning work: identifying the test files that exercise
the affected surface and recording them as detection candidates. No project
code, tests, or test execution are part of this phase.

## Boundary Context

- **In scope**: behavior-preserving stabilization of the Twisted HTTP/2
  download handler (drop the experimental marking) and privatization of its API
  (supporting modules/classes become private), plus the test-file detection
  candidates that cover that surface.
- **Out of scope**: the httpx-based handler, HTTP/1.1 handler internals, and any
  runtime behavior change to request/response handling.
- **Adjacent expectations**: import paths and `DOWNLOAD_HANDLERS` string paths
  documented for users keep working or gain an explicit migration path.

## Requirements

### Requirement 1: Non-experimental status

**Objective:** As a Scrapy user, I want the Twisted-based HTTP/2 download
handler to be documented as production-ready, so that I can rely on it without
being warned away.

#### Acceptance Criteria

1. When the HTTP/2 download handler documentation is rendered, the system shall
   not state that the handler is experimental or unsuitable for production.
2. When a crawler enables the handler, the system shall not emit an
   experimental-use warning attributable to it.
3. The system shall keep the documented `twisted-http2-handler` reference
   target resolvable.

### Requirement 2: Privatized handler API

**Objective:** As a Scrapy maintainer, I want the handler's supporting API to
be private, so that internal refactors do not create backward-compatibility
obligations.

#### Acceptance Criteria

1. Where the HTTP/2 client package is referenced, the system shall expose it
   only through a private module path in its final state.
2. When the download handler is configured through `DOWNLOAD_HANDLERS`, the
   configured path shall resolve to the handler actually shipped by the
   package.
3. If an old public path is removed, then the system shall fail loudly rather
   than silently degrading.

### Requirement 3: Test-file detection for the change

**Objective:** As a benchmark consumer, I want the test files that cover the
affected surface to be identified, so that change validation can be scoped
without running the suite.

#### Acceptance Criteria

1. When the detect phase completes, the system shall record exactly one
   `detection-draft.json` in the method planning directory containing only a
   `candidates` array.
2. The system shall record, for each candidate, a repository-relative test
   path, the relevant symbols, and a reason tied to the change.
3. The system shall not execute tests or modify project code or tests while
   producing the draft.
