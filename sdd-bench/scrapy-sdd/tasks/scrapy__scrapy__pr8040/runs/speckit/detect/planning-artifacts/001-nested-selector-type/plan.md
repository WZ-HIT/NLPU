# Implementation Plan: Nested Selector Type Inference

**Branch**: `001-nested-selector-type` | **Date**: 2026-09-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-nested-selector-type/spec.md`

## Summary

Scrapy currently assigns an HTML default whenever a selector is constructed without an explicit type, even when parsel is constructing a nested selector from an existing parsed root. The implementation should limit response-derived defaults to top-level construction where no root was supplied, allowing parsel to infer the type for nested roots.

## Technical Context

**Language/Version**: Python 3.9+ project code, verified with Python 3.11 in this environment

**Primary Dependencies**: parsel and Scrapy's response classes

**Storage**: N/A

**Testing**: pytest through the repository's tox configuration

**Target Platform**: Cross-platform Python library

**Project Type**: Library

**Performance Goals**: No measurable regression in selector construction or selection

**Constraints**: Preserve response object behavior and explicit selector types; do not require a newer parsel API than the project supports

**Scale/Scope**: One focused selector constructor behavior with regression coverage in the selector tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository constitution remains the unratified template and defines no enforceable project-specific gates. The change is a small compatibility correction, preserves public behavior outside nested inference, and adds no dependency or architectural complexity. Gate result: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/001-nested-selector-type/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── selector-type-inference.md
├── tasks.md
└── detection-draft.json
```

### Source Code (repository root)

```text
scrapy/
└── selector/
    └── unified.py

tests/
└── test_selector.py
```

**Structure Decision**: Use the existing single-package library structure and place regression coverage in the existing selector test module.

## Complexity Tracking

No constitutional violations or added complexity.
