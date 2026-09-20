# Implementation Plan: Re-enable DirtyReactorAggregateError Tests

**Branch**: `re-enable-dirty-reactor-tests` | **Date**: 2026-09-19 | **Spec**: [spec.md](spec.md)

## Summary

Restore three tests that currently skip on Windows with the asyncio reactor because of
historical `DirtyReactorAggregateError` failures. The change removes the obsolete skip
conditions while retaining the tests' existing assertions.

## Technical Context

**Language/Version**: Python 3.9+ (repository test matrix; current runtime Python 3.11)

**Primary Dependencies**: pytest, pytest-twisted, Twisted

**Storage**: N/A

**Testing**: pytest with Scrapy's reactor and platform test markers

**Target Platform**: Scrapy's supported CI matrix, specifically Windows with asyncio

**Project Type**: Python library

**Performance Goals**: N/A

**Constraints**: Do not alter product code or test assertions; keep the change test-only

**Scale/Scope**: Three test methods in two test modules

## Constitution Check

No project-specific constitution has been ratified; the repository's existing contribution
and CI conventions govern the change. The plan does not introduce new architecture,
dependencies, interfaces, or product behavior.

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

**Structure Decision**: Reuse the existing pytest modules and the shared HTTP test base.
No new test module is needed.

## Complexity Tracking

No constitution violations or added complexity.
