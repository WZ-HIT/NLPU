# Implementation Plan: Improve Scrapy Utils Test Coverage

**Branch**: `001-improve-utils-test-coverage` | **Date**: 2026-09-20 | **Spec**: `specs/001-improve-utils-test-coverage/spec.md`

## Summary

Detect the test files that should carry regression coverage for pull request 7841. Discovery is read-only: inspect the utility modules changed by the pull request, map each changed symbol to the test modules that exercise it (or that the repository convention designates), and record the result as a detection draft. No code, tests, or test runs are part of this stage.

## Technical Context

**Language/Version**: Python 3.11+ (repository supports CPython and PyPy)
**Primary Dependencies**: pytest, zlib, pyOpenSSL (>= 24.3.0), cryptography (>= 41.0.5), Twisted
**Storage**: N/A
**Testing**: pytest only; the detect stage inspects tests and never executes them
**Target Platform**: Cross-platform Python library
**Project Type**: Library
**Performance Goals**: N/A
**Constraints**: Read-only repository; writes restricted to the mounted planning directory
**Scale/Scope**: Utility test files for compression (`scrapy/utils/_compression.py`), SSL (`scrapy/utils/ssl.py`), and callable introspection (`scrapy/utils/python.py`)

## Constitution Check

The project constitution at `.specify/memory/constitution.md` is still an unfilled template, so no concrete gates apply. The plan keeps the production and test trees untouched and confines all writes to planning artifacts inside the mounted planning directory.

## Project Structure

### Documentation (mounted planning directory)

```text
specs/001-improve-utils-test-coverage/
├── spec.md
├── plan.md
├── tasks.md
├── detection-draft.json
└── checklists/
    └── requirements.md
```

### Relevant Repository Paths

Changed production modules:

```text
scrapy/utils/_compression.py
scrapy/utils/python.py
scrapy/utils/ssl.py
```

Detected candidate test paths:

```text
tests/test_utils_python.py                         (exists at base commit)
tests/test_downloadermiddleware_httpcompression.py (exists at base commit)
tests/test_utils_ssl.py                            (expected new test module)
tests/test_utils_compression.py                    (expected new test module)
```

**Structure Decision**: Standard single-project layout. All method artifacts stay inside the feature planning directory; repository code and tests are never written.

## Detection Method

1. Extract the changed symbols from the pull request description: `_inflate()`, `ffi_buf_to_string()`/`_ffi_buf_to_string()`, and `get_func_args_dict()`/`get_func_args()`.
2. Search `tests/` for existing references to those symbols to find files that already exercise them.
3. For modules without a dedicated test file, apply the repository's `tests/test_utils_<module>.py` convention.
4. Record every candidate with `path`, `symbols`, and `reason`, using repository-relative paths.

## Phase 0/1 Design Artifacts

`research.md`, `data-model.md`, `contracts/`, and `quickstart.md` are not applicable here: this feature adds no data model or external interface, and the detect stage produces no runnable validation guide. The detection draft and the task list are the complete outputs.

## Complexity Tracking

No constitution violations.
