# Implementation Plan: Open-in-Browser ReDoS Test Stability

**Branch**: `open-in-browser-redos-test-stability` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/workspace/specs/spec.md`

## Summary

Stabilize the two `open_in_browser` ReDoS regression checks so they do not fail merely because a slow interpreter exceeds a fixed 20 ms CPU allowance. The change is expected to be test-only and must preserve a meaningful failure condition for catastrophic processing.

## Technical Context

**Language/Version**: Python 3.10 and later

**Primary Dependencies**: pytest; Scrapy's existing HTTP response test utilities

**Storage**: N/A

**Testing**: pytest

**Target Platform**: Scrapy's supported CPython versions on normal and slow CI interpreters

**Project Type**: Python library

**Performance Goals**: Preserve detection of catastrophic processing without treating normal linear processing as a failure on slow interpreters

**Constraints**: Test-only scope; no production behavior change; no removal, skip, or unconditional xfail of either regression check; no weakening of the pathological inputs

**Scale/Scope**: Two test functions in one test module

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository constitution is still the unratified template and defines no enforceable project-specific gates. No gate violation is introduced. The plan retains the existing public behavior, keeps the change narrowly scoped, and preserves regression coverage.

Post-design re-check: PASS. The design remains test-only and introduces no new structure, dependency, or public interface.

## Project Structure

### Documentation (this feature)

```text
/workspace/specs/
├── spec.md
├── plan.md
├── research.md
├── quickstart.md
├── tasks.md
├── detection-draft.json
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
scrapy/
└── utils/
    └── response.py

tests/
└── test_utils_response.py
```

**Structure Decision**: The repository is a single Python library. The only expected implementation target is `tests/test_utils_response.py`; `scrapy/utils/response.py` is reference code for behavior and is not expected to change.

## Complexity Tracking

No constitution violations or added complexity require justification.
