# Implementation Plan: Re-enable DirtyReactorAggregateError Tests

**Branch**: `001-reenable-dirty-reactor-tests` | **Date**: 2026-09-17 | **Spec**: `specs/spec.md`

**Input**: Pull request 8073 at base `11079cb1c85b9e75a39a7269943c69d1a975d485`

## Summary

Identify the test files and symbols carrying historical
`DirtyReactorAggregateError` skip comments so a later update stage can re-enable
or reassess them. The change is test-only. Detection uses repository search and
direct inspection; tests are neither run nor modified.

## Technical Context

**Language/Version**: Python >=3.10

**Primary Dependencies**: Twisted >=21.7.0, pytest, pytest-twisted

**Storage**: N/A

**Testing**: pytest with Twisted reactor tests (collection/inspection only in
the detect stage)

**Target Platform**: Scrapy-supported operating systems and reactor
implementations, including Windows asyncio where the historical skip applies

**Project Type**: Python library

**Performance Goals**: N/A

**Constraints**: Read-only project and test trees; no test execution; write
only under `/workspace/specs`

**Scale/Scope**: Three skip occurrences across two test files

## Constitution Check

The repository constitution is an unfilled template, so there are no ratified
project-specific gates. The planning task follows the stronger runtime
constraints supplied by the benchmark: no tests, no project-code changes, and
planning writes are confined to `/workspace/specs`.

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
└── detection-draft.json
```

### Source Code (repository root)

```text
tests/
├── test_downloader_handler_twisted_ftp.py
└── utils/
    └── bases/
        └── download_handlers_http.py
```

**Structure Decision**: Scrapy is a single Python project. Detection targets only
the existing test tree. Contract artifacts are omitted because the task exposes
no external interface.

## Complexity Tracking

No constitution violations.
