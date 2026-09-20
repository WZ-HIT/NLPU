# Tasks: Support IDNA-2003-only domains

**Input**: Design documents in `specs/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`

**Tests**: Do not run tests in this planning phase. Test tasks below describe
future implementation work only.

## Phase 1: Setup

**Purpose**: Confirm the compatibility boundary and current Twisted behavior.

- [ ] T001 Inspect Twisted IDNA helper imports and identify every Scrapy-facing consumer in `scrapy/resolver.py`, `scrapy/core/downloader/contextfactory.py`, and downloader endpoints.
- [ ] T002 [P] Document representative ASCII, IDNA-2003-only, and IDNA-2008 hostnames for future verification in `specs/quickstart.md`.

---

## Phase 2: Foundational

**Purpose**: Establish the import-time compatibility hook.

- [ ] T003 Implement a localized Twisted IDNA helper wrapper with a preferred conversion and legacy fallback in `scrapy/utils/url.py`.
- [ ] T004 Activate the helper patch once during package import in `scrapy/__init__.py`.
- [ ] T005 Ensure the wrapper preserves original errors when both conversions fail and does not change ordinary ASCII results.

**Checkpoint**: The helper is installed before requests create resolvers or TLS endpoints.

---

## Phase 3: User Story 1 - Reach a legacy internationalized hostname (Priority: P1)

**Goal**: Allow IDNA-2003-only names to reach resolution with an ASCII hostname.

**Independent Test**: Exercise the compatibility helper with a legacy-only name and verify successful stable ASCII conversion.

- [ ] T006 [P] [US1] Add helper-level IDNA-2003 fallback coverage in `tests/test_utils_url.py`.
- [ ] T007 [P] [US1] Add resolver-facing hostname conversion coverage in `tests/test_resolver.py`.
- [ ] T008 [US1] Verify request construction and downstream resolution use the same converted hostname in `tests/test_http_request.py` and `tests/test_crawl.py`.

**Checkpoint**: The reported legacy hostname no longer fails before DNS resolution.

---

## Phase 4: User Story 2 - Preserve existing IDNA behavior (Priority: P2)

**Goal**: Retain existing behavior for ASCII and modern internationalized names.

**Independent Test**: Run focused request, TLS, and downloader tests with existing hostnames.

- [ ] T009 [P] [US2] Add regression checks for ASCII and preferred IDNA conversion results in `tests/test_utils_url.py`.
- [ ] T010 [P] [US2] Verify TLS hostname conversion remains correct in `tests/test_core_downloader.py`.
- [ ] T011 [US2] Verify Twisted HTTP/1.1 hostname handling remains unchanged in `tests/test_downloader_handlers.py`.
- [ ] T012 [US2] Confirm import-time activation in `tests/test_toplevel.py`.

**Checkpoint**: Legacy support is added without changing established hostname mappings.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T013 [P] Add a concise compatibility note in `docs/news.rst`.
- [ ] T014 Review the shim for upstream-removal conditions and document the rationale in `scrapy/utils/url.py`.

---

## Dependencies & Execution Order

- Phase 1 has no dependencies.
- Phase 2 depends on Phase 1 and blocks both user stories.
- US1 and US2 can proceed independently after Phase 2.
- Polish follows the desired user stories.

## Parallel Opportunities

- T002 can run alongside T001.
- T006, T007, T009, T010, and T013 touch different files and can run in parallel.

## Implementation Strategy

Deliver the import-time hook and IDNA-2003 fallback first (US1), then validate
compatibility behavior (US2). Do not run the test suite in this planning phase.
