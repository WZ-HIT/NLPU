# Tasks: Address VCS workflow warnings

## Phase 1: Setup

- [ ] T001 Confirm the workflow command and environment in `.github/workflows/tests-vcs-deps.yml`
- [ ] T002 [P] Inventory the development-branch dependency sets in `tox.ini`
- [ ] T003 [P] Capture the warning output reported by a VCS workflow run

## Phase 2: Foundational

- [ ] T004 Classify every warning by origin and stability
- [ ] T005 Review the existing warning policy in `pyproject.toml` and `scrapy/__init__.py`
- [ ] T006 Review dependency version gates in `scrapy/utils/_deps_compat.py`

## Phase 3: User Story 1 - Keep the VCS dependency run actionable (Priority: P1)

### Tests for User Story 1

- [ ] T007 [P] [US1] Validate shared TLS/handler warning handling in `tests/utils/bases/download_handlers_http.py`
- [ ] T008 [P] [US1] Validate downloader context-factory warnings in `tests/test_core_downloader.py`
- [ ] T009 [P] [US1] Validate the Twisted HTTP/1.1 handler cases in `tests/test_downloader_handler_twisted_http11.py`
- [ ] T010 [P] [US1] Validate the httpx2 handler cases in `tests/test_downloader_handler_httpx.py`
- [ ] T011 [P] [US1] Validate the HTTP/2 handler cases in `tests/test_downloader_handler_twisted_http2.py`
- [ ] T012 [P] [US1] Validate crawler TLS certificate assertions in `tests/test_crawl.py`
- [ ] T013 [P] [US1] Validate HTTP/2 protocol certificate assertions in `tests/test_http2_client_protocol.py`
- [ ] T014 [P] [US1] Validate Scrapy warning plumbing in `tests/test_utils_deprecate.py`
- [ ] T015 [P] [US1] Validate the tox dependency contract in `tests/test_dependencies.py`

### Implementation

- [ ] T016 [US1] Apply the narrowest warning or dependency-compatibility change
- [ ] T017 [US1] Document any dependency-origin warning that remains filtered

## Phase 4: Polish

- [ ] T018 [P] Confirm no repository-wide warning suppression was introduced
- [ ] T019 Run the candidate tests from `specs/detection-draft.json`
- [ ] T020 Run the `vcs-deps` workflow validation

## Dependencies

T001-T006 precede T007-T017. T018-T020 follow the focused implementation.

## Independent Test

Run the `vcs-deps` environment and retain the complete warning output for review.
