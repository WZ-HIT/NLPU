# Feature Specification: Improve Scrapy Utils Test Coverage

**Feature Branch**: `001-improve-utils-test-coverage`
**Created**: 2026-09-20
**Status**: Draft
**Input**: Pull request 7841: Improve the test coverage of `scrapy.utils`.

## User Scenarios & Testing

### User Story 1 - Detect Regression Tests (Priority: P1)

As a maintainer, I need the test files affected by the utility bug fixes identified before implementation, so regression coverage is added in the right places.

**Independent Test**: Review the detected candidate paths and confirm each one either already exercises a changed utility symbol or follows the repository's naming convention for the module that changed.

**Acceptance Scenarios**:

1. **Given** the `_inflate()` termination fix, **When** candidates are detected, **Then** both the dedicated compression test path and the existing middleware compression test path are present.
2. **Given** the `ffi_buf_to_string()` self-recursion fix, **When** candidates are detected, **Then** the dedicated SSL utility test path is present.
3. **Given** the `get_func_args_dict()` partial fix, **When** candidates are detected, **Then** the existing `scrapy.utils.python` test file is present.

### Edge Cases

- Deflate data followed by extra bytes must terminate instead of looping forever.
- A partial callable bound to a positional value that happens to equal a parameter name (for example `partial(f, "b")`) must still report the remaining parameter names.
- The deprecated `ffi_buf_to_string()` must delegate to `_ffi_buf_to_string()` without recursing.

## Requirements

- **FR-001**: Detection MUST return repository-relative test paths.
- **FR-002**: Every candidate MUST include `path`, `symbols`, and `reason`.
- **FR-003**: Detection MUST cover the compression, SSL, and callable-introspection changes described by the pull request.
- **FR-004**: Planning MUST NOT modify production code or tests, and MUST NOT run the test suite.
- **FR-005**: The detection draft MUST contain only a top-level `candidates` array.

## Success Criteria

- **SC-001**: The detection draft contains exactly one top-level `candidates` array.
- **SC-002**: All three changed areas (compression, SSL utils, callable introspection) have at least one candidate test path.
- **SC-003**: All candidate paths are repository-relative and live under `tests/`.

## Assumptions

- Candidate paths include files the pull request is expected to add: the base commit has no `tests/test_utils_ssl.py` and no `tests/test_utils_compression.py`, while `tests/test_utils_python.py` and `tests/test_downloadermiddleware_httpcompression.py` already exist and exercise the changed symbols.
- New utility tests follow the repository's existing `tests/test_utils_<module>.py` convention.
- `tests/test_downloadermiddleware_httpcompression.py` remains a valid integration candidate for `_inflate()` because it already covers rawdeflate decoding and `_DecompressionMaxSizeExceeded` reporting.
