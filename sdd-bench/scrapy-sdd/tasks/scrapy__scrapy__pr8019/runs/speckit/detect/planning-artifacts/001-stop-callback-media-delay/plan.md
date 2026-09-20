# Implementation Plan: Stop Sleeping 100 ms Before Callbacks and Media Results

**Branch**: `001-stop-callback-media-delay` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-stop-callback-media-delay/spec.md`

## Summary

Replace the fixed 100 ms wait (`scrapy.utils.defer._defer_sleep_async()` →
`await sleep(0.1)`) that precedes spider callback invocation, downloader/middleware
error handling and media results with a zero-delay "process pending I/O" yield
(`_process_pending_io()` → `await sleep(0)` twice). In the media pipeline, notify
waiting deferreds directly instead of through `call_later(_DEFER_DELAY, ...)`, and
yield once before caching the result. Deprecated public helpers keep their current
delay and deprecation warnings; no public API changes.

## Technical Context

**Language/Version**: Python >= 3.10 (`requires-python = ">=3.10"` in `pyproject.toml`)

**Primary Dependencies**: Twisted >= 21.7.0 (reactor/`Deferred`), optional asyncio reactor path

**Storage**: N/A (in-memory `SpiderInfo` cache for media fingerprints)

**Testing**: pytest with `pytest-twisted` / `pytest-asyncio` and the `--reactor` option (`default`, `asyncio`, `none`); helpers in `tests/utils/decorators.py`

**Target Platform**: Cross-platform library (CPython and PyPy)

**Project Type**: Single project — a scraping framework/library with a CLI (`scrapy/` package, `tests/` suite)

**Performance Goals**: Remove a fixed ~100 ms cost per callback and per media result; per-callback engine overhead below 1 ms (SC-001, SC-002)

**Constraints**: Preserve the "pending readers/writers run first" ordering guarantee (FR-002, FR-005); no public API/setting/signal changes (FR-011); keep de-duplication semantics (FR-012)

**Scale/Scope**: 6 production files touched; no new modules; no schema or configuration changes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unratified template (placeholders only),
so no project-specific gates are defined. Default gates applied for this plan:

- **No public API break**: passes — `_defer_sleep_async` / `_process_pending_io` are private; deprecated helpers unchanged (FR-010, FR-011).
- **Behavior-preserving refactor**: passes — the safety yield is retained in every migrated call site (FR-002, FR-006, FR-007).
- **Testability**: passes — every requirement maps to existing pytest modules (see `tasks.md` and `quickstart.md`).
- **No new dependencies**: passes.

No violations, so Complexity Tracking is not required.

## Project Structure

### Documentation (this feature)

```text
specs/001-stop-callback-media-delay/
├── plan.md              # This file ($speckit-plan command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
├── checklists/          # Requirements quality checklist ($speckit-specify output)
└── tasks.md             # Phase 2 output ($speckit-tasks command - NOT created by $speckit-plan)
```

### Source Code (repository root)

```text
scrapy/
├── utils/
│   ├── defer.py                     # helper definition + deprecated delayed helpers
│   └── asyncio.py                   # sleep() used by the helper (0 seconds supported)
├── core/
│   ├── scraper.py                   # call_spider_async(): callback invocation
│   ├── spidermw.py                  # scrape_response_async(): exception path
│   └── downloader/
│       ├── __init__.py              # Downloader._download(): failure path
│       └── middleware.py            # download_async(): exception path
└── pipelines/
    └── media.py                     # cached result, download start, waiter notification

tests/
├── test_pipeline_media.py           # imports the renamed helper; media cache/waiters
├── test_utils_defer.py              # unit tests for scrapy/utils/defer.py
├── test_pipeline_crawl.py           # end-to-end media download through pipelines
├── test_crawl.py                    # end-to-end callbacks/errbacks
├── test_spidermiddleware.py         # spider middleware exception paths
├── test_downloadermiddleware.py     # downloader middleware exception paths
├── test_core_scraper.py             # scraper callback/error handling
└── test_request_left.py             # downloader slot release / request_left_downloader
```

**Structure Decision**: Single-project layout; the change is an internal refactor spread
across the event-loop-adjacent modules listed above. Files that only define/consume the
yield helper are `scrapy/utils/defer.py` (definition) and the five call-site modules.

## Complexity Tracking

No constitution violations; table intentionally omitted.
