# Implementation Plan: Open Non-Text Responses in Browser via Content-Type

**Branch**: `001-open-in-browser-content-type` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/workspace/specs/spec.md`

## Summary

Extend the public browser-opening utility so a generic response can be opened when its `Content-Type` identifies a media type with a conventional local-file extension. Preserve the existing specialized behavior for HTML responses (`.html` plus base-link injection) and non-HTML textual responses (`.txt`). Update the command-line view workflow to delegate non-text responses to the utility instead of rejecting them before the media type is considered. Keep missing or unknown media types as explicit unsupported-response failures.

## Technical Context

**Language/Version**: Python 3.10 or newer, matching `pyproject.toml`.

**Primary Dependencies**: Scrapy, Twisted, and w3lib; use the Python standard library for media-type extension mapping and temporary-file creation. No new dependency is required.

**Storage**: Temporary local files created by the existing browser-opening utility. No persistent storage or schema change.

**Testing**: pytest, including utility-level tests in `tests/test_utils_response.py` and command-level tests in `tests/test_commands.py`.

**Target Platform**: Cross-platform Python library and command-line interface. The browser command remains platform-dependent, but extension selection must be platform-independent.

**Project Type**: Library plus command-line tool.

**Performance Goals**: Preserve existing utility performance and the current protections against pathological HTML. Media-type parsing is constant-time for normal headers; no response body decoding is allowed.

**Constraints**: Do not modify or re-encode binary bodies. Preserve current HTML base-link behavior and non-HTML text behavior. Do not derive a generic response's extension from its URL. Do not add configuration or user opt-in. This planning turn must not edit project code or tests or run tests.

**Scale/Scope**: One public utility in `scrapy/utils/response.py`, one command workflow in `scrapy/commands/view.py`, and focused utility and command tests. Shell behavior follows automatically because it exposes the utility.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution at `.specify/memory/constitution.md` is still the unpopulated template. It defines no enforceable project-specific principles or governance gates. The plan therefore passes with the repository's standard quality expectations: preserve public behavior, add focused regression coverage, avoid unnecessary dependencies, and keep the change minimal.

Post-design re-check: PASS. The design adds no storage, dependency, service, or project-structure complexity. The only behavior change is the intended extension of generic-response support.

## Project Structure

### Documentation (this feature)

```text
specs/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/
│   └── requirements.md
├── contracts/
│   └── open-in-browser.md
├── tasks.md
└── detection-draft.json
```

### Source Code (repository root)

```text
scrapy/
├── commands/
│   └── view.py
├── http/
│   └── response/
│       ├── __init__.py
│       └── text.py
├── shell.py
└── utils/
    └── response.py

tests/
├── test_commands.py
├── test_command_shell.py
├── test_utils_response.py
├── mockserver/
│   └── http.py
└── utils/
    └── cmdline.py
```

**Structure Decision**: Keep the implementation in the existing response utility and command modules. The utility owns media-type interpretation and temporary-file creation. The command workflow only removes its premature non-text rejection and delegates to the utility. Tests remain in the existing utility and command test modules.

## Complexity Tracking

No constitution violations or unjustified complexity.
