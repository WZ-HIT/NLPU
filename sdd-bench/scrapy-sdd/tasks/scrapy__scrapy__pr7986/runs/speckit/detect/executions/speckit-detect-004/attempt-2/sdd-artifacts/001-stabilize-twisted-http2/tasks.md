# Tasks: Stabilize and Privatize the Twisted HTTP/2 Handler

**Input**: Design documents from `specs/001-stabilize-twisted-http2/`

**Prerequisites**: `plan.md`, `spec.md`

**Tests**: Candidate tests are identified for later verification. Do not run tests or modify tests during Detect planning.

## Phase 1: Setup

- [ ] T001 Confirm the supported `H2DownloadHandler` path and inventory internal HTTP/2 symbols in `scrapy/core/http2/agent.py`, `scrapy/core/http2/protocol.py`, and `scrapy/core/http2/stream.py`
- [ ] T002 Identify all documentation statements marking the Twisted HTTP/2 handler experimental in `docs/topics/download-handlers.rst` and `docs/news.rst`

## Phase 2: Foundational

- [ ] T003 Define the private naming map for implementation classes, exceptions, and constants used across `scrapy/core/http2/`
- [ ] T004 Confirm the HTTPX handler's experimental behavior remains separate in `scrapy/core/downloader/handlers/_httpx.py` and `scrapy/core/downloader/handlers/_base_streaming.py`

## Phase 3: User Story 1 - Stable handler documentation (Priority: P1)

**Goal**: Present the Twisted HTTP/2 handler as supported rather than experimental.

**Independent Test**: Load the documented handler configuration and confirm HTTP/2 behavior without an experimental warning.

- [ ] T005 [US1] Remove the experimental warning for the Twisted handler from `docs/topics/download-handlers.rst` while retaining explicit limitations
- [ ] T006 [US1] Add the unreleased release-note entry documenting the stabilization in `docs/news.rst`
- [ ] T007 [US1] Verify every remaining `H2DownloadHandler` documentation reference points to the supported handler path

## Phase 4: User Story 2 - Private implementation API (Priority: P2)

**Goal**: Keep only the documented handler entry point public and rename implementation-only classes.

**Independent Test**: Import the supported handler successfully and confirm updated internal imports resolve after class renames.

- [ ] T008 [P] [US2] Privatize agent and connection-pool symbols and update references in `scrapy/core/http2/agent.py`
- [ ] T009 [P] [US2] Privatize protocol and factory symbols and update references in `scrapy/core/http2/protocol.py`
- [ ] T010 [P] [US2] Privatize stream symbols and update references in `scrapy/core/http2/stream.py`
- [ ] T011 [US2] Update imports and type references in `scrapy/core/downloader/handlers/http2.py`
- [ ] T012 [US2] Update internal comments and type references in `scrapy/core/downloader/contextfactory.py`

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T013 Update direct implementation imports in `tests/test_http2_client_protocol.py`
- [ ] T014 Verify handler-level behavior coverage in `tests/test_downloader_handler_twisted_http2.py`
- [ ] T015 Run formatting, linting, and the focused tests only after implementation is complete

## Dependencies & Execution Order

- Setup precedes all implementation.
- Foundational naming decisions precede the three parallel privatization tasks.
- Handler import updates depend on the three implementation modules.
- Test updates depend on the finalized private names.
- The focused tests run only after all source and test changes are complete.

## Parallel Opportunities

- T008, T009, and T010 touch separate implementation modules and can proceed in parallel after T003.
- T013 and T014 concern separate test files and can proceed in parallel after T011.

## Implementation Strategy

Complete Setup and Foundational work, then deliver US1 and US2 together because the documentation and API stabilization describe the same release-facing change. Use the two candidate test files as the primary focused verification set.
