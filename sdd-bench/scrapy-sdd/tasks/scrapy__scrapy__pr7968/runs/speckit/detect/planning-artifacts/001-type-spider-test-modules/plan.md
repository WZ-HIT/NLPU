# Implementation Plan: Typed Spider Test Modules

**Branch**: `001-type-spider-test-modules` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-type-spider-test-modules/spec.md`

## Summary

Add explicit parameter/return annotations to the spider-related test modules and their test helpers
so the project's strict static analysis pass type-checks their bodies, then drop those modules from
the per-module "untyped definitions" exclusion block in `pyproject.toml`. Annotations only — no
runtime behaviour changes — validated by re-running static analysis and the affected test modules.

## Technical Context

**Language/Version**: Python 3.10+ (project baseline; postponed-annotation import already in use)

**Primary Dependencies**: pytest (configured asyncio reactor), Twisted `Deferred`, strict static type checking, ruff, pylint (test-suite toolchain)

**Storage**: N/A (test-only change; `tests/sample_data` fixtures unchanged)

**Testing**: the project's pytest suite for the affected modules; strict static type checking for the annotation contract; lint/format checks for style

**Target Platform**: Linux/macOS/Windows CI matrix (no platform-specific code touched)

**Project Type**: Library (Scrapy framework) with an in-repository test suite

**Performance Goals**: N/A — annotations are evaluated lazily and add no measurable test-run cost

**Constraints**: Diff must stay annotation-only (FR-004, SC-004); inline suppressions limited to intentionally-invalid-call tests (SC-002)

**Scale/Scope**: 7 files in the primary scope (5 test modules + 2 test-helper modules) drawn from the spider cluster of the static-analysis exclusion list, plus `pyproject.toml` bookkeeping

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the unratified project template (all sections are placeholders),
so no project-specific gates are defined. Repository-derived gates are applied instead:

- **Annotation-only change**: PASS — edits limited to annotations, typing-only imports, and the
  exclusion list (FR-004).
- **Test behaviour preserved**: PASS — no assertion/fixture/helper body may be rewritten (FR-004, FR-007).
- **Static analysis strictness**: PASS — modules must pass with the per-module exclusion removed (FR-003).
- **Style compliance**: PASS — postponed-annotation import plus built-in generics/union syntax (FR-005).

Post-Phase 1 re-check: unchanged; no design artifact requires a gate exception, so Complexity Tracking
stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-type-spider-test-modules/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (detection-draft contract)
├── checklists/
│   └── requirements.md  # Specification quality checklist
└── tasks.md             # Phase 2 output ($speckit-tasks)
```

The detect-phase output `detection-draft.json` is written to the root of the mounted planning
directory (`specs/detection-draft.json`), not inside this feature directory.

### Source Code (repository root)

```text
tests/
├── spiders.py                                   # spider fixtures/classes used by spider tests
├── utils/
│   └── bases/
│       └── spider.py                            # shared TestSpiderBase test class
├── test_spider.py                               # Spider / feed-spider tests
├── test_spider_crawl.py                         # CrawlSpider tests
├── test_spider_sitemap.py                       # SitemapSpider tests
├── test_spidermiddleware_output_chain.py        # spider-middleware output chain tests
└── test_spidermiddleware_process_start.py       # spider-middleware process_start tests

pyproject.toml                                   # static-analysis exclusion bookkeeping
```

**Structure Decision**: Single-project layout. The change is confined to the existing `tests/` tree
plus static-analysis configuration in `pyproject.toml`; no new directories or modules are introduced.

## Complexity Tracking

No constitution (or repository-derived) gate violations, so no tracking table is required.
