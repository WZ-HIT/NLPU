# Implementation Plan: Type the Remaining Exempt Test Modules

**Branch**: `8017-type-last-untyped-test-modules` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Scrapy PR #8017, "Type the last tests.* modules under check_untyped_defs = false"

## Summary

Annotate the test code governed by the final `check_untyped_defs = false` mypy override, then remove the exemption block. The work is limited to test modules and `pyproject.toml`; runtime behavior must remain unchanged. This planning run stops before implementation and writes only planning artifacts under `/workspace/specs`.

## Technical Context

**Language/Version**: Python 3.10 minimum; mypy CI runs on Python 3.10

**Primary Dependencies**: mypy 2.1.0, pytest, Twisted, queuelib, itemadapter/itemloaders, lxml/parsel, and existing test helpers

**Storage**: N/A

**Testing**: `mypy scrapy tests`; focused pytest modules for the affected tests

**Target Platform**: Linux/macOS/Windows CI, CPython and PyPy test environments

**Project Type**: Library with pytest test suite

**Performance Goals**: No runtime performance impact; typing and test execution remain within existing CI budgets

**Constraints**: No production behavior changes; Python 3.10-compatible annotations; preserve test collection and runtime semantics

**Scale/Scope**: 14 mypy-exempt test modules, comprising 12 standalone test files and 2 package test modules

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository constitution is an unratified placeholder and defines no project-specific principles or gates. The plan therefore applies these default gates: preserve runtime behavior, keep changes within the requested test-typing scope, and verify with the existing mypy/test toolchain. No violation is anticipated.

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
├── checklists/
│   └── requirements.md
└── detection-draft.json
```

### Source Code (repository root)

```text
pyproject.toml
tests/
├── test_cmdline/
│   └── __init__.py
├── test_downloaderslotssettings.py
├── test_dupefilters.py
├── test_extension_statsmailer.py
├── test_extension_throttle.py
├── test_linkextractors.py
├── test_logformatter.py
├── test_mail.py
├── test_pqueues.py
├── test_scheduler_base.py
├── test_settings/
│   └── __init__.py
├── test_squeues.py
├── test_squeues_request.py
└── test_stats.py
```

**Structure Decision**: Use the existing single-project layout. The implementation touches only the listed test modules and the mypy override in `pyproject.toml`; no contracts directory is needed because this feature exposes no external interface.

## Complexity Tracking

No constitution violations or additional architectural complexity are required.
