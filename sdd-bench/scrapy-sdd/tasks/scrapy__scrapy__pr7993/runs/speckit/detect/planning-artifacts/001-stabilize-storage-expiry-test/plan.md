# Implementation Plan: Stabilize Storage Expiry Test

**Branch**: `001-stabilize-storage-expiry-test` | **Date**: 2026-09-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-stabilize-storage-expiry-test/spec.md`

## Summary

Stabilize the shared cache-storage expiration test by making its reference time deterministic. The test must verify a successful pre-expiry retrieval even when the runner is delayed, then deliberately advance beyond the expiration threshold and verify a miss. Existing filesystem and DBM variants must retain coverage, and production code must not change.

## Technical Context

**Language/Version**: Python 3.10 or newer

**Primary Dependencies**: pytest and test-time mocking utilities already available in the repository

**Storage**: Filesystem cache storage and DBM cache storage, including gzip and custom DBM variants

**Testing**: pytest; not executed during this planning-only task

**Target Platform**: Scrapy CI runners on supported platforms

**Project Type**: Library with a pytest test suite

**Performance Goals**: Eliminate the timing-dependent false failure without adding sleeps or materially slowing the test

**Constraints**: Modify only test code in the eventual implementation; no production source or public behavior changes; no test execution during this planning task

**Scale/Scope**: One shared test file and one shared test method, inherited by existing concrete storage test classes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository constitution contains only template placeholders and no ratified project-specific principles. No gate is violated by this bounded test-stability change. The work keeps production behavior unchanged, preserves existing test coverage, and avoids adding dependencies or external interfaces.

## Project Structure

### Documentation (this feature)

```text
specs/001-stabilize-storage-expiry-test/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

No `contracts/` artifact is produced because this change exposes no external or programmatic interface.

### Source Code (repository root)

```text
scrapy/
└── extensions/
    └── httpcache.py

tests/
└── test_downloadermiddleware_httpcache.py
```

**Structure Decision**: The repository is a single Python library. The eventual change is confined to the shared `StorageTestMixin.test_storage` test in `tests/test_downloadermiddleware_httpcache.py`; production cache-storage behavior in `scrapy/extensions/httpcache.py` is read-only context.

## Complexity Tracking

No constitution violations or added complexity require justification.
