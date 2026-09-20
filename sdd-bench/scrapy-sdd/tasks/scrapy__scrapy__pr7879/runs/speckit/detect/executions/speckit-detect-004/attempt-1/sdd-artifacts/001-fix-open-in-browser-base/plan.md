# Implementation Plan: Fix open_in_browser base insertion without a head

**Branch**: `001-fix-open-in-browser-base` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/workspace/specs/001-fix-open-in-browser-base/spec.md`

## Summary

Make browser previews usable for HTML responses that have no real head element. The existing preview path detects comments and inserts a base element only after a real head tag. The change will add a fallback that creates a valid head/base section for headless documents while preserving the current behavior for normal documents, existing bases, comments, text responses, and malformed input.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: Twisted, w3lib, standard-library `re`; pytest for verification

**Storage**: N/A

**Testing**: pytest; the direct module is `tests/test_utils_response.py`

**Target Platform**: Cross-platform Python library

**Project Type**: Library

**Performance Goals**: Preserve the existing fast path for very large malformed HTML inputs

**Constraints**: Do not change the public function signature, return behavior, or plain-text handling

**Scale/Scope**: One utility function in `scrapy/utils/response.py`; regression coverage in `tests/test_utils_response.py`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The checked-in constitution contains template placeholders rather than ratified project-specific principles. No additional gates are defined. The change is a narrow bug fix with no new dependency, storage, or broad architectural impact.

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-open-in-browser-base/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── checklists/requirements.md
└── detection-draft.json
```

### Source Code (repository root)

```text
scrapy/utils/response.py       # browser-preview preparation
tests/test_utils_response.py   # direct unit coverage
tests/test_commands.py         # optional end-to-end consumer coverage for `scrapy view`
```

**Structure Decision**: Use the existing single-library layout and keep the fix local to the response utility.

## Complexity Tracking

No constitution violations or additional complexity are required.
