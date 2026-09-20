# Implementation Plan: Safe Shutdown Signal Logging

**Feature Branch**: `detect-scrapy-pr8022` | **Date**: 2026-09-19 | **Spec**: [spec.md](spec.md)

**Input**: PR 8022, "Do not log from the shutdown signal handlers"

## Summary

Move shutdown logging out of OS signal-handler bodies. For Twisted-backed
processes, queue the existing logging calls with `reactor.callFromThread()`.
For reactorless async processes, queue them with
`loop.call_soon_threadsafe()`. Preserve handler escalation, message text, and
shutdown behavior.

## Technical Context

**Language/Version**: Python 3.9+ within the repository

**Primary Dependencies**: Twisted reactor APIs and asyncio

**Storage**: Not applicable

**Testing**: Existing pytest suite; affected tests exercise crawler shutdown
helpers and subprocess shutdown behavior. Tests are not run during this
planning-only task.

**Target Platform**: Scrapy-supported desktop/server platforms

**Project Type**: Single Python library and CLI

**Performance Goals**: No synchronous logging in signal handlers; no added
shutdown latency

**Constraints**: Preserve existing messages, escalation order, and public APIs

**Scale/Scope**: Two shutdown implementations in `scrapy/crawler.py`

## Constitution Check

The repository constitution is still its placeholder template and defines no
enforceable project-specific gates. No violations are introduced by this
planning-only feature.

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
├── checklists/requirements.md
└── detection-draft.json
```

### Source Code (repository root)

```text
scrapy/
└── crawler.py

tests/
├── test_crawler.py
└── test_crawler_subprocess.py
```

**Structure Decision**: The behavioral change is confined to
`scrapy/crawler.py`; the tests most directly coupled to the affected helpers
and shutdown messages are the candidate test files.

## Phase 0: Research

Research is recorded in [research.md](research.md). No unresolved
clarifications remain.

## Phase 1: Design and Contracts

The state model is recorded in [data-model.md](data-model.md). No external
interface contract is added. Validation scenarios are recorded in
[quickstart.md](quickstart.md).

## Post-Design Constitution Check

No change to public interfaces, dependencies, governance, or complexity. The
design passes the available constitution checks.
