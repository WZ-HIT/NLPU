# Tasks: Improve Scrapy Utils Test Coverage

**Input**: Design documents from `specs/001-improve-utils-test-coverage/`

## Phase 1: Detection Setup

- [ ] T001 Confirm the mounted planning directory is `specs/` and keep `scrapy/` and `tests/` read-only, recorded in `specs/001-improve-utils-test-coverage/plan.md`
- [ ] T002 Extract the changed utility symbols from the pull request description into `specs/001-improve-utils-test-coverage/spec.md`
- [ ] T003 Search `tests/` for existing references to `_inflate`, `ffi_buf_to_string`, `get_func_args_dict`, and `get_func_args` to identify files already exercising them

## Phase 2: Candidate Detection

- [ ] T004 [US1] Record the callable-introspection candidate `tests/test_utils_python.py` with symbol `get_func_args_dict` in `specs/001-improve-utils-test-coverage/detection-draft.json`
- [ ] T005 [P] [US1] Record the SSL candidate `tests/test_utils_ssl.py` with symbol `ffi_buf_to_string` in `specs/001-improve-utils-test-coverage/detection-draft.json`
- [ ] T006 [P] [US1] Record the compression candidates `tests/test_utils_compression.py` and `tests/test_downloadermiddleware_httpcompression.py` with symbol `_inflate` in `specs/001-improve-utils-test-coverage/detection-draft.json`
- [ ] T007 [US1] Validate in `specs/001-improve-utils-test-coverage/detection-draft.json` that every candidate has `path`, `symbols`, and `reason`, and that every path is repository-relative under `tests/`

## Phase 3: Handoff

- [ ] T008 Confirm exactly one `detection-draft.json` exists inside the mounted planning directory and that its top level contains only `candidates`

## Dependencies & Execution Order

T001-T003 block candidate detection. T004-T006 update the same JSON file, so they are recorded sequentially. T007 and T008 depend on all candidates being present.

## Implementation Strategy

Produce the minimum complete candidate set first, then validate schema and path scope. Nothing is executed or modified in the repository; only detection artifacts are written.
