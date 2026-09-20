# Tasks: Mandatory zstd decompression

**Input**: Design documents in `specs/`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`

**Tests**: Test tasks are included because the PR changes existing test
expectations. This planning task does not execute them.

## Phase 1: Setup

**Purpose**: Confirm target files and dependency boundaries.

- [ ] T001 Review current zstd references in `pyproject.toml`, `tox.ini`, `scrapy/utils/_compression.py`, `scrapy/downloadermiddlewares/httpcompression.py`, and `tests/test_downloadermiddleware_httpcompression.py`
- [ ] T002 [P] Review zstd installation and optional-extra documentation in `docs/intro/install.rst`, `docs/topics/downloader-middleware.rst`, and `docs/topics/optimize.rst`

---

## Phase 2: Foundational

**Purpose**: Establish the standard/backport import and dependency contract.

- [ ] T003 Add `backports-zstd>=1.3.0; python_version < '3.14'` to the core dependencies in `pyproject.toml`
- [ ] T004 Remove the `zstd` optional-dependency extra from `pyproject.toml`
- [ ] T005 Update zstd imports in `scrapy/utils/_compression.py` to use `compression.zstd` on Python 3.14+ and `backports.zstd` on earlier versions
- [ ] T006 Remove obsolete `zstandard` pins and source dependency entries from `tox.ini`

**Checkpoint**: A default supported environment always has a zstd decoder.

---

## Phase 3: User Story 1 - Decode zstd responses by default (Priority: P1) MVP

**Goal**: Advertise and decode zstd without an optional extra.

**Independent Test**: Process all valid zstd fixtures through a default
middleware instance and verify decoded bodies and removed headers.

### Tests for User Story 1

- [ ] T007 [P] [US1] Update `TestHttpCompression.test_process_request` in `tests/test_downloadermiddleware_httpcompression.py` to expect unconditional zstd advertisement
- [ ] T008 [P] [US1] Remove the optional-dependency gate from `TestHttpCompression.test_process_response_zstd` in `tests/test_downloadermiddleware_httpcompression.py`
- [ ] T009 [US1] Remove or replace `TestHttpCompression.test_process_response_zstd_unsupported` in `tests/test_downloadermiddleware_httpcompression.py`

### Implementation for User Story 1

- [ ] T010 [US1] Add `zstd` unconditionally to `ACCEPTED_ENCODINGS` and remove `find_spec()` detection from `scrapy/downloadermiddlewares/httpcompression.py`
- [ ] T011 [US1] Remove the zstd installation warning branch from `HttpCompressionMiddleware._warn_unknown_encoding` in `scrapy/downloadermiddlewares/httpcompression.py`
- [ ] T012 [US1] Adapt `_unzstd()` in `scrapy/utils/_compression.py` to the standard/backport `ZstdDecompressor` API
- [ ] T013 [P] [US1] Update zstd dependency and extra documentation in `docs/intro/install.rst`, `docs/topics/downloader-middleware.rst`, and `docs/topics/optimize.rst`

**Checkpoint**: Valid zstd responses decode from a default installation.

---

## Phase 4: User Story 2 - Preserve decompression safety limits (Priority: P2)

**Goal**: Keep zstd size and warning behavior equivalent to other encodings.

**Independent Test**: Run zstd bomb, warning-size, and truncation scenarios
without dependency skips.

### Tests for User Story 2

- [ ] T014 [P] [US2] Remove optional-dependency gates from the zstd compression-bomb tests in `tests/test_downloadermiddleware_httpcompression.py`
- [ ] T015 [P] [US2] Remove optional-dependency gates from the zstd download-warning tests in `tests/test_downloadermiddleware_httpcompression.py`
- [ ] T016 [P] [US2] Remove the optional-dependency gate from `TestHttpCompression.test_process_truncated_response_zstd` in `tests/test_downloadermiddleware_httpcompression.py`

### Implementation for User Story 2

- [ ] T017 [US2] Preserve incremental `_check_max_size()` enforcement in `_unzstd()` in `scrapy/utils/_compression.py`
- [ ] T018 [US2] Verify unsupported trailing-input and truncated-stream handling in `_unzstd()` in `scrapy/utils/_compression.py`

**Checkpoint**: zstd obeys the same safety and warning controls as existing encodings.

---

## Phase 5: User Story 3 - Use the standard zstd API consistently (Priority: P3)

**Goal**: Remove the separate `zstandard` package contract.

**Independent Test**: Inspect dependency metadata and imports on both sides of
the Python 3.14 boundary.

### Tests for User Story 3

- [ ] T019 [P] [US3] Remove all test references to `find_spec("zstandard")` and `_skip_if_no_zstd` from `tests/test_downloadermiddleware_httpcompression.py`

### Implementation for User Story 3

- [ ] T020 [US3] Remove remaining runtime references to `zstandard` from `scrapy/utils/_compression.py` and `scrapy/downloadermiddlewares/httpcompression.py`
- [ ] T021 [US3] Remove obsolete zstd installation guidance from `docs/intro/install.rst`, `docs/topics/downloader-middleware.rst`, and `docs/topics/optimize.rst`

**Checkpoint**: No supported installation requires the `zstandard` package.

---

## Phase 6: Polish

- [ ] T022 Verify no source or test file contains an obsolete optional-zstd assumption
- [ ] T023 Run the project checks and zstd-focused tests in the implementation environment
- [ ] T024 Confirm behavior on Python versions before and after the 3.14 boundary

## Dependencies & Execution Order

- Setup can start immediately.
- Foundational tasks T003-T006 block all user stories.
- US1 depends on Foundational and is the MVP.
- US2 depends on US1's decoder and middleware behavior.
- US3 depends on US1 but can update metadata/documentation in parallel.
- Polish depends on all selected stories.

## Parallel Opportunities

- T001 and T002.
- T007, T008, and T013 after Foundational.
- T014, T015, and T016.
- T019 and T021.

## Implementation Strategy

Complete the dependency and import foundation first, then deliver the default
decode path (US1). Adapt safety tests next (US2), and finish by removing all
remaining `zstandard` assumptions (US3). US1 is the MVP.
