# Implementation Plan: Generalize Internal Component Construction

**Branch**: pull request 7808 | **Date**: 2026-09-20 | **Spec**: `specs/spec.md`

## Summary

Replace remaining internal direct `from_crawler()` calls with
`build_from_crawler()` so optional component constructors follow the documented
Scrapy component contract. Preserve the `from_crawler()` path when present and
fall back to `__init__()` otherwise.

## Technical Context

**Language/Version**: Python, project-supported versions

**Primary Dependencies**: Scrapy, Twisted

**Storage**: N/A

**Testing**: pytest and the project test suite

**Target Platform**: Cross-platform Python environments supported by Scrapy

**Project Type**: Library

**Constraints**: Planning only; do not run tests or modify project code/tests

**Scale/Scope**: Internal constructor call sites in crawler setup, managers,
extensions, and robots.txt handling

## Constitution Check

The repository constitution is an unfilled template. No additional project
gates can be derived from it. The plan follows the feature specification and
keeps all changes within the requested planning-only scope.

## Project Structure

### Planning Artifacts

```text
specs/
├── spec.md
├── plan.md
├── tasks.md
└── detection-draft.json
```

### Relevant Repository Areas

```text
scrapy/
├── crawler.py
├── core/downloader/__init__.py
├── core/scraper.py
├── downloadermiddlewares/robotstxt.py
├── extensions/memusage.py
├── extensions/statsmailer.py
└── utils/misc.py

tests/
├── test_crawler.py
├── test_downloadermiddleware.py
├── test_spidermiddleware.py
├── test_pipelines.py
├── test_middleware.py
├── test_extension_statsmailer.py
├── test_extension_memusage.py
├── test_downloadermiddleware_robotstxt.py
├── test_robotstxt_interface.py
├── test_utils_misc/__init__.py
└── utils/bases/spider.py
```

**Structure Decision**: The repository uses a single Python package with tests
mirroring component families. The implementation changes are localized to
constructor call sites and the tests above are the candidate regression and
behavioral coverage.

## Phase 0: Research

### Decision: Use `build_from_crawler()` for component construction

**Rationale**: It is the documented component construction contract and already
selects `from_crawler()` when available, otherwise calls `__init__()`, and
rejects `None`.

**Alternatives considered**: Retaining direct `from_crawler()` calls would keep
the inconsistency and force every internal component to expose a class method.

### Decision: Preserve spider lifecycle construction

**Rationale**: Spider classes have crawler-specific lifecycle requirements and
`Crawler._create_spider()` is not merely generic component construction.

### Decision: Treat deprecated mail paths as behavior-preserving changes

**Rationale**: Only constructor dispatch changes; warning and notification
behavior remains intact.

## Phase 1: Design

### Data Model

No persistent data model is introduced.

| Construct | Inputs | Output / invariant |
|-----------|--------|--------------------|
| `build_from_crawler(objcls, crawler, *args, **kwargs)` | Class, crawler, optional constructor args | Instance; `from_crawler` preferred; `__init__` fallback; `None` rejected |
| Manager constructors | Crawler | Fully initialized manager |
| Item processor constructor | Crawler and `ITEM_PROCESSOR` class | Initialized item processor |
| Log formatter constructor | Crawler and `LOG_FORMATTER` class | Initialized formatter |
| Robots parser constructor | Crawler and robots body | Initialized parser |

### Contracts

No public API is added. Existing component construction behavior is the
contract:

```python
if hasattr(objcls, "from_crawler"):
    instance = objcls.from_crawler(crawler, *args, **kwargs)
else:
    instance = objcls(*args, **kwargs)
```

An instance of `None` must raise `TypeError`.

### Quickstart Validation

1. Configure a component class that defines only `__init__()`.
2. Start or initialize the crawler path that creates that component.
3. Confirm the component is created.
4. Configure a component with `from_crawler()` and confirm that method is used.
5. Run the candidate regression tests selected in `detection-draft.json` when
   implementation is authorized.
