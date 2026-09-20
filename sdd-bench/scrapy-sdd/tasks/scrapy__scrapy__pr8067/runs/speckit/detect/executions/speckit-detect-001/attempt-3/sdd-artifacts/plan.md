# Implementation Plan: Browser Preview for Non-Text Responses

**Branch**: `speckit-detect` | **Date**: 2026-09-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/workspace/specs/spec.md`
(upstream task: scrapy/scrapy PR #8067, base commit `3857c6906b2da51e12ca6005434512b7704fd659`)

**Note**: This template is filled in by the `$speckit-plan` command; its definition describes the execution workflow.

## Summary

`scrapy.utils.response.open_in_browser` and `scrapy view` currently support only
HTML and text responses: any other response raises
`TypeError: Unsupported response type: ...` (helper) or logs
`Cannot view a non-text response.` (command). This feature makes both paths work
for non-text resources by deriving the temporary preview file's extension from
the response `Content-Type` media type, with a deterministic fallback when no
extension can be derived, while leaving the hardened HTML and text paths
untouched. No new runtime dependency is required: the standard-library
media-type registry already ships with the supported interpreter.

## Technical Context

**Language/Version**: Python >= 3.10 (project `requires-python`), plus the
matching Python 3.11 development environment used by the test suite

**Primary Dependencies**: Twisted (`twisted.web.http`), `w3lib.html`; standard
library modules already imported by the touched modules (`tempfile`,
`webbrowser`, `os`, `re`) and the standard-library media-type registry for the
new extension lookup. No new third-party dependency (FR-008).

**Storage**: N/A (temporary files under the system temp directory, unchanged)

**Testing**: pytest (project suite under `tests/`), driven through `tox` in CI;
this planning stage does not execute tests (`SDD_AGENT_NO_TESTS=1`).

**Target Platform**: Cross-platform Python library/CLI (Linux, macOS, Windows);
existing Windows-specific preview-file handling must keep working.

**Project Type**: Single project - a Python library plus its `scrapy` CLI

**Performance Goals**: No measurable regression in preview latency; the HTML
path must stay linear-time on adversarial input (existing Redos guards), and
the new lookup must be a constant-time registry call per invocation.

**Constraints**: Preserve the `open_in_browser(response, _openfunc=...)`
signature and import path; change only the branch that currently raises; keep
the raw body byte-for-byte identical in the written file.

**Scale/Scope**: Two production modules (`scrapy/utils/response.py`,
`scrapy/commands/view.py`), their two existing test modules, and release notes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled project template: it
defines no ratified principles, version, or governance rules. No gate can be
evaluated against it, so this plan falls back to the repository's own
conventions, which it satisfies:

| Gate (repository convention) | Status | Evidence |
|---|---|---|
| Backward compatibility of public API | PASS | Signature and import path unchanged (FR-007). |
| No new runtime dependency | PASS | Standard-library registry only (FR-008). |
| Existing behavior preserved unless the request changes it | PASS | HTML/text paths untouched; only the previously-raising branch changes (FR-003, FR-004). |
| Behavior covered by tests | PASS | Existing modules `tests/test_utils_response.py` and `tests/test_commands.py` already own these code paths. |
| User-visible change documented | PASS | Release-notes entry added in the Polish phase. |

No violations, so Complexity Tracking is empty. Post-design re-check: still PASS
(the design adds one lookup rule inside one existing function and removes one
guard, with no new module, dependency, or public surface).

## Project Structure

### Documentation (this feature)

```text
/workspace/specs/
├── spec.md              # Feature specification ($speckit-specify)
├── plan.md              # This file ($speckit-plan)
├── research.md          # Phase 0 output ($speckit-plan)
├── data-model.md        # Phase 1 output ($speckit-plan)
├── quickstart.md        # Phase 1 output ($speckit-plan)
├── contracts/           # Phase 1 output ($speckit-plan)
│   └── open_in_browser.md
├── checklists/
│   └── requirements.md  # Spec quality checklist ($speckit-specify)
├── tasks.md             # Phase 2 output ($speckit-tasks)
└── detection-draft.json # Detect-phase candidate test files
```

### Source Code (repository root)

```text
scrapy/
├── utils/
│   └── response.py         # open_in_browser: extension resolution (new branch)
├── commands/
│   └── view.py             # scrapy view: stop refusing non-text responses
└── shell.py                # exposes open_in_browser as the view shell variable
docs/
└── news.rst                # release-notes entry
tests/
├── test_utils_response.py  # unit tests for open_in_browser
└── test_commands.py        # TestViewCommand: CLI-level scrapy view tests
```

**Structure Decision**: Single project. The change is confined to the existing
`scrapy/utils/response.py` helper and the `scrapy/commands/view.py` command that
uses it; no new modules or packages are introduced. Documentation artifacts for
this planning stage live in the mounted planning directory `/workspace/specs`
(repository source is read-only in this stage).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None - no Constitution Check violations.
