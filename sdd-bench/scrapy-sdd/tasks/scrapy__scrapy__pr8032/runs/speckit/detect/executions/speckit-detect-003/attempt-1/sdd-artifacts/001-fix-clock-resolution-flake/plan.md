# Implementation Plan: Deterministic Response-Based File Path Test

**Branch**: `001-fix-clock-resolution-flake` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-fix-clock-resolution-flake/spec.md`

**Note**: This template is filled in by the `$speckit-plan` command; its
definition describes the execution workflow.

## Summary

Make the `test_file_path_from_response` test in `tests/test_pipeline_files.py`
deterministic on platforms with a coarse system clock (Windows). The test
asserts that a response-aware `FilesPipeline` subclass re-downloads an item
whose pre-existing file sits at the response-less path, using `FILES_EXPIRES = 0`
to disable the up-to-date shortcut. The mocked store reports the pre-existing
file with `last_modified = time.time()`; on Windows two consecutive `time.time()`
reads can return the same value, so the computed age is `0`, the freshness check
concludes "still fresh", and the result becomes `uptodate` instead of
`downloaded`. The fix removes the dependence on the live wall clock by giving
the mocked store a timestamp that is unambiguously in the past, keeping every
assertion intact and adding no sleeps.

## Technical Context

**Language/Version**: Python 3.9+ (project baseline in `pyproject.toml`), test
run reported on Python 3.11

**Primary Dependencies**: Scrapy (`scrapy.pipelines.files`, `scrapy.pipelines.media`),
Twisted, `itemadapter`, `pytest`

**Storage**: Local filesystem through the `FSFilesStore` (mocked `stat_file` in
the test; no real store access needed)

**Testing**: `pytest` with the project's own coroutine-test decorators
(`tests.utils.decorators.coroutine_test`) and `unittest.mock`

**Target Platform**: Cross-platform library; the failing platform is Windows
(coarse ~15 ms system clock resolution)

**Project Type**: Library (single project)

**Performance Goals**: The single test stays in the sub-second range; no added
sleep or polling

**Constraints**: No network access; the test must remain fully simulated and
offline; deterministic outcome independent of host clock resolution

**Scale/Scope**: One test method in `tests/test_pipeline_files.py`, with the
shared helpers in that module unaffected

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unratified placeholder template
(it contains `[PROJECT_NAME]` and `[PRINCIPLE_1_NAME]` placeholders), so no
project-specific gates are defined. The plan therefore relies on the repository's
own conventions:

| Gate | Status | Notes |
|------|--------|-------|
| Determinism / no flaky tests | PASS | The change removes the only wall-clock dependency from the test. |
| No production behavior change | PASS | The change is confined to a test module; nothing under `scrapy/` is touched. |
| No new dependencies | PASS | Only existing test utilities and `unittest.mock` are used. |
| Offline execution | PASS | The store and download remain mocked. |
| Keep existing coverage | PASS | All existing assertions are preserved, including the `.pdf` extension check. |

No violations to justify; the Complexity Tracking section is intentionally empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-clock-resolution-flake/
├── plan.md              # This file ($speckit-plan command output)
├── research.md          # Phase 0 output ($speckit-plan command)
├── data-model.md        # Phase 1 output ($speckit-plan command)
├── quickstart.md        # Phase 1 output ($speckit-plan command)
├── contracts/           # Phase 1 output ($speckit-plan command)
├── checklists/          # Spec quality checklist ($speckit-specify command)
└── tasks.md             # Phase 2 output ($speckit-tasks command - NOT created by $speckit-plan)
```

### Source Code (repository root)

```text
scrapy/
├── pipelines/
│   ├── files.py         # FilesPipeline.file_path / _onsuccess (freshness decision)
│   └── media.py         # MediaPipeline.media_to_download (shared up-to-date path)
└── utils/

tests/
├── test_pipeline_files.py   # Target module: TestFilesPipeline.test_file_path_from_response
├── test_pipeline_images.py  # Sibling subclass tests (ImagesPipeline) - regression surface
├── test_pipeline_media.py   # Shared media pipeline tests - regression surface
├── test_pipeline_crawl.py   # Integration coverage of the files pipeline - regression surface
└── utils/
    ├── media_pipelines.py   # mocked_download_func helper used by the test
    └── decorators.py        # coroutine_test helper used by the test
```

**Structure Decision**: Single-project library layout. The change is confined to
the existing test module `tests/test_pipeline_files.py`; no new directories or
production modules are introduced.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations were identified, so this section is intentionally empty.
