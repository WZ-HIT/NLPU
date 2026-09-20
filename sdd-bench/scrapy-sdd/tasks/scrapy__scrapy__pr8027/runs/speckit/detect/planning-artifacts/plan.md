# Implementation Plan: Download Delay Crawl Coverage

**Branch**: `detect` | **Date**: 2026-09-19 | **Spec**: `spec.md`

**Input**: Pull request task in `/task-input/task.md`

## Summary

Strengthen the crawl-level fixed and randomized download-delay tests by ensuring they visit enough pages to produce stable timing measurements instead of skipping. The implementation is test-only: adjust crawl scenario parameters and preserve the delayed-versus-control assertions.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: Scrapy, Twisted, pytest, pytest-twisted

**Storage**: N/A

**Testing**: pytest with the repository mock server and crawl helpers

**Target Platform**: Scrapy CI and developer test environments

**Project Type**: Python library

**Performance Goals**: Enough page visits for meaningful timing while keeping runtime bounded

**Constraints**: No production changes, no test execution during detect planning, cross-platform compatibility

**Scale/Scope**: One crawl test module and its timing helper

## Constitution Check

The repository constitution is a placeholder, so no concrete project-specific gates are defined. The change respects the inferred principles of minimal scope, test-backed behavior, and no production impact.

## Project Structure

### Documentation (this feature)

```text
specs/
|-- spec.md
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- tasks.md
`-- detection-draft.json
```

### Source Code (repository root)

```text
tests/
|-- test_crawl.py
`-- spiders.py
```

**Structure Decision**: The behavior is exercised by the crawl-level delay tests in `tests/test_crawl.py`, with page generation supplied by `FollowAllSpider` in `tests/spiders.py`.

## Phase 0: Research

Research is consolidated in `research.md`. The key decision is to increase the crawl workload for the existing delay scenarios rather than introduce a skip condition.

## Phase 1: Design

Timing entities and validation are captured in `data-model.md`. No external interface is introduced, so no `contracts/` artifact is needed. Validation steps are in `quickstart.md`.

## Complexity Tracking

No constitution violations or added architectural complexity.
