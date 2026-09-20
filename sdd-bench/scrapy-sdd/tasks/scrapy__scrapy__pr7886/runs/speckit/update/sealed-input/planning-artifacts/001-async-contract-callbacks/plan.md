# Implementation Plan: Asynchronous Callbacks in Spider Contracts

**Branch**: `001-async-contract-callbacks` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-async-contract-callbacks/spec.md`

## Summary

Spider contracts currently reject callbacks that return an asynchronous result:
the pre-hook and post-hook wrappers in `scrapy/contracts/__init__.py` detect
`CoroutineType` / `AsyncGenerator` results and raise
`TypeError("Contracts don't support async callbacks")`, and the callback wrapper
installed by `ContractsManager._clean_req()` converts every result with
`iterate_spider_output()` without awaiting it. This plan replaces those hard
rejections with the same awaitable handling the crawl path already uses: results
are normalized through `scrapy.utils.spider.iterate_spider_output()` and
`scrapy.utils.defer`, so coroutine results become `Deferred`s that the check runner
drives, while async generators are consumed as async iterables. Contract
bookkeeping (`@returns`, `@scrapes`, pre/post hooks, failure/error attribution)
keeps its current semantics, and synchronous callbacks keep their current code path
and output.

## Technical Context

**Language/Version**: Python 3.10+ (`requires-python = ">=3.10"` in `pyproject.toml`; the
development environment for this task runs CPython 3.11)

**Primary Dependencies**: Twisted (`Deferred`, `deferred_from_coro` via
`scrapy.utils.defer`), plus the existing `iterate_spider_output()` helper; pytest with
`pytest-twisted` for the test suite

**Storage**: N/A

**Testing**: pytest; focused run is `pytest tests/test_contracts.py`, with
`pytest tests/test_command_check.py` covering the `scrapy check` command path. Full
matrix is driven by `tox`.

**Target Platform**: Cross-platform Python library (the Scrapy package), consumed both
as a library and through the `scrapy` CLI

**Project Type**: Single project (framework/library) with an in-repo test suite

**Performance Goals**: No measurable regression for synchronous contract checks; the
asynchronous path is bounded by the awaited callback itself, with no extra reactor
round-trips beyond what the crawl path already incurs.

**Constraints**: No new runtime dependencies; synchronous behaviour and reported
outcome formats unchanged; type annotations must stay valid for the project's mypy
configuration; ruff and formatting checks stay clean; changes limited to contract
checking (crawl-time async behaviour is already supported).

**Scale/Scope**: Small, focused change. Primary files: `scrapy/contracts/__init__.py`
(behaviour), `tests/test_contracts.py` (unit expectations), optionally
`tests/test_command_check.py` (command-level integration) and
`docs/topics/contracts.rst` (documented example).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` in this repository still contains the unfilled
constitution template (placeholder principle names such as `[PRINCIPLE_1_NAME]`), so
no project-specific gates are currently ratified. The default gates applied to this
plan are:

| Gate | Status | Notes |
|------|--------|-------|
| Single-project structure preserved | PASS | Change stays inside the existing `scrapy/` package and `tests/` suite. |
| No new dependencies | PASS | Reuses Twisted and existing Scrapy utilities. |
| Backwards compatibility | PASS | Synchronous callbacks keep the same code path and reported outcomes (FR-008). |
| Testability | PASS | Both unit-level and command-level checks are reachable; test tasks are enumerated in `tasks.md`. |
| Scope discipline | PASS | Only contract checking changes; crawl-time async support is untouched. |

No violations require justification, so Complexity Tracking remains empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-async-contract-callbacks/
├── plan.md              # This file ($speckit-plan command output)
├── spec.md              # Feature specification ($speckit-specify command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── contract-hooks.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output ($speckit-tasks command)
```

### Source Code (repository root)

```text
scrapy/
├── contracts/
│   ├── __init__.py      # Contract base class, ContractsManager; async rejection to replace
│   └── default.py       # Built-in contracts (@url, @returns, @scrapes, ...) - expectations only
├── commands/
│   └── check.py         # `scrapy check` command: runs contracts and reports results
└── utils/
    ├── spider.py        # iterate_spider_output(): coroutine/async-generator normalization
    └── defer.py         # deferred_from_coro(), ensure_awaitable() helpers

docs/
└── topics/
    └── contracts.rst    # User-facing contract documentation (example coverage)

tests/
├── test_contracts.py        # Unit tests for contracts, including async callback cases
└── test_command_check.py    # `scrapy check` command tests (project-level integration)
```

**Structure Decision**: Single-project layout. Implementation is confined to the
existing `scrapy.contracts` package, a library feature of the Scrapy framework; the
`scrapy check` command consumes it. No new packages or modules are introduced.

## Complexity Tracking

No Constitution Check violations, so no entries are required here.
