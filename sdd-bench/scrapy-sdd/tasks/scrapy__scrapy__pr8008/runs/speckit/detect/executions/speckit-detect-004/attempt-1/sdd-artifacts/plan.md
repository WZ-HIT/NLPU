# Implementation Plan: Stabilize Slow-Pipeline Spider-Start Test

**Branch**: `fix-flaky-slow-pipeline` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/spec.md`

## Summary

Make `test_slow_pipeline` independent of event-loop completion order while preserving strict ordered comparisons for every other test. The implementation is confined to `tests/test_spider_start.py`: extend the shared `_test_spider` helper with an order-sensitive default and opt only the equally delayed slow-pipeline case into multiset comparison.

## Technical Context

**Language/Version**: Python 3.9+ as supported by Scrapy at the base revision

**Primary Dependencies**: Scrapy, pytest, Twisted/asyncio test integrations, `itemadapter` where needed for generic item access

**Storage**: N/A

**Testing**: pytest with the repository's coroutine test decorators and asyncio/Twisted marks

**Target Platform**: Scrapy CI on Linux, macOS, and Windows

**Project Type**: Python library with test suite

**Performance Goals**: No measurable runtime impact on the test suite

**Constraints**: Test-only change; preserve existing assertions and exact item cardinality; do not run implementation tests during planning

**Scale/Scope**: One test module, one helper signature, one call site

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository constitution at this revision is still the unpopulated Spec Kit template, so it defines no ratified project-specific gates. The change nonetheless satisfies the generic gates: it is minimal, test-only, avoids public API changes, preserves existing behavior by default, and directly addresses a reproducible reliability defect.

Post-design re-check: PASS. No production interface, persistence, security, or dependency change is introduced.

## Project Structure

### Documentation (this feature)

```text
/workspace/specs/
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
tests/
└── test_spider_start.py   # Shared helper and affected slow-pipeline test
```

**Structure Decision**: No new source structure is needed. The repair belongs in the existing focused test module.

## Complexity Tracking

No constitution violations or added complexity are required.
