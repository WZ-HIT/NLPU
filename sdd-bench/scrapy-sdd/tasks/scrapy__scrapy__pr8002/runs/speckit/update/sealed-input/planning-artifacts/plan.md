# Implementation Plan: Merge LxmlLinkExtractor Test Classes

**Branch**: `8002-merge-linkextractor-tests` | **Date**: 2026-09-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/workspace/specs/spec.md`

## Summary

Consolidate the hidden shared link extractor test base and the concrete LxmlLinkExtractor test class into one discoverable test class in `tests/test_linkextractors.py`. Preserve every existing behavior test and the separate LxmlParserLinkExtractor suite. This is a test-only refactor with no production-code changes.

## Technical Context

**Language/Version**: Python 3.10 or newer

**Primary Dependencies**: pytest, lxml, w3lib

**Storage**: N/A

**Testing**: pytest

**Target Platform**: Repository-supported Python environments

**Project Type**: Python library

**Performance Goals**: No runtime performance change; test-suite runtime should remain effectively unchanged

**Constraints**: Modify only the link extractor tests; preserve all test assertions and conditional skips; do not change production code

**Scale/Scope**: One test module; 41 existing test methods, of which 38 cover the public LxmlLinkExtractor and 3 cover the internal parser extractor

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository constitution is still the unratified template and defines no project-specific gates. The plan therefore applies the default quality gates: keep the change minimal, preserve behavior, avoid unrelated production changes, and retain independently runnable tests. Result: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── detection-draft.json
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
scrapy/
└── linkextractors/
    ├── __init__.py
    └── lxmlhtml.py

tests/
└── test_linkextractors.py
```

**Structure Decision**: The change is confined to `tests/test_linkextractors.py`. Production modules are shown only to establish the public behavior boundary and must remain untouched.

## Complexity Tracking

No constitution violations or added complexity.
