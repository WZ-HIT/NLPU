---

description: "Task list for SSLKEYLOGFILE support"
---

# Tasks: SSLKEYLOGFILE Support

**Input**: Design documents from `/specs/001-sslkeylogfile-support/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: Test tasks are included because the feature affects security-sensitive TLS behavior. This planning phase does not execute them.

## Phase 1: Setup

- [ ] T001 Confirm the adopted configuration name and compatibility expectations in `docs/topics/settings.rst`
- [ ] T002 Identify the installed TLS API versions used by the repository in `pyproject.toml`

---

## Phase 2: Foundational

- [ ] T003 Implement shared key-log destination resolution and standard record-writing behavior in `scrapy/utils/ssl.py`
- [ ] T004 Add a key-log helper for stdlib `ssl.SSLContext` instances in `scrapy/utils/ssl.py`
- [ ] T005 Add a key-log helper for pyOpenSSL contexts in `scrapy/utils/ssl.py`

**Checkpoint**: Both TLS implementations can write standard records through one opt-in policy.

---

## Phase 3: User Story 1 - Capture TLS session keys for diagnosis (Priority: P1) - MVP

**Goal**: Opted-in HTTPS connections emit usable key-log records.

**Independent Test**: Configure the destination, complete HTTPS requests through both TLS implementations, and inspect the records.

### Tests for User Story 1

- [ ] T006 [P] [US1] Add focused utility tests for disabled and enabled key-log behavior in `tests/test_utils_ssl.py`
- [ ] T007 [P] [US1] Add Twisted context-factory key-log tests in `tests/test_core_downloader.py`
- [ ] T008 [P] [US1] Add stdlib HTTPX handler key-log coverage in `tests/test_downloader_handler_httpx.py`

### Implementation for User Story 1

- [ ] T009 [US1] Apply the shared stdlib key-log helper in `scrapy/core/downloader/handlers/_httpx.py`
- [ ] T010 [US1] Apply the shared pyOpenSSL/twisted key-log helper in `scrapy/core/downloader/contextfactory.py`
- [ ] T011 [US1] Verify HTTP/1.1 and HTTP/2 inherit context-factory key logging in `scrapy/core/downloader/handlers/http11.py` and `scrapy/core/downloader/handlers/http2.py`

**Checkpoint**: The primary diagnostic workflow works for every built-in HTTPS path.

---

## Phase 4: User Story 2 - Avoid credential leakage during normal crawls (Priority: P2)

**Goal**: Key logging remains absent unless explicitly enabled.

**Independent Test**: Run HTTPS requests without the destination and verify no key-log output is created.

### Tests for User Story 2

- [ ] T012 [P] [US2] Add a default-disabled assertion to `tests/test_utils_ssl.py`
- [ ] T013 [P] [US2] Add a default-disabled assertion to `tests/test_core_downloader.py`

### Implementation for User Story 2

- [ ] T014 [US2] Ensure every helper is a no-op when no destination is configured in `scrapy/utils/ssl.py`

**Checkpoint**: Ordinary crawls do not expose TLS secrets.

---

## Phase 5: User Story 3 - Consistent HTTPS handler behavior (Priority: P2)

**Goal**: All built-in HTTPS handlers honor the same configuration and output format.

**Independent Test**: Repeat the enabled scenario for Twisted HTTP/1.1, Twisted HTTP/2, and HTTPX.

### Tests for User Story 3

- [ ] T015 [P] [US3] Add HTTPS handler coverage in `tests/test_downloader_handler_twisted_http11.py`
- [ ] T016 [P] [US3] Add HTTPS handler coverage in `tests/test_downloader_handler_twisted_http2.py`
- [ ] T017 [P] [US3] Add shared HTTPS-base coverage where behavior is common in `tests/utils/bases/download_handlers_http.py`

### Implementation for User Story 3

- [ ] T018 [US3] Reconcile handler-specific setup so all built-in HTTPS handlers use the shared policy in `scrapy/core/downloader/contextfactory.py` and `scrapy/core/downloader/handlers/_httpx.py`

**Checkpoint**: Handler choice does not change key-log semantics.

---

## Phase 6: Polish

- [ ] T019 [P] Document enabling, output location, and security implications in `docs/topics/settings.rst`
- [ ] T020 [P] Add release-note text in `docs/news.rst`
- [ ] T021 Review error handling and avoid including secrets in exception messages in `scrapy/utils/ssl.py`
- [ ] T022 Validate `quickstart.md` manually after implementation

---

## Dependencies & Execution Order

- Phase 1 has no dependencies.
- Phase 2 depends on Phase 1.
- Phases 3, 4, and 5 depend on Phase 2; story tests and implementation can run in parallel where files do not overlap.
- Phase 6 depends on the selected user stories.

## Parallel Opportunities

- T006, T007, and T008 use separate test files.
- T012 and T013 use separate test files.
- T015, T016, and T017 use separate test files.
- T019 and T020 edit separate documentation files.

## Implementation Strategy

Complete the shared utility first, then validate the P1 stdlib and Twisted paths. Finish with default-disabled and cross-handler coverage before documentation and release notes. This planning task stops before implementation and does not execute any test command.
