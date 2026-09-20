# Implementation Plan: Python 3.15 CI Compatibility

**Branch**: `001-python-315-ci` | **Date**: 2026-09-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/spec.md`

## Summary

Add Python 3.15 prerelease coverage to the CI matrix where dependencies permit and preserve `scrapy.utils.misc.walk_modules_iter` behavior on that interpreter. The planning scope also records the repository-relative tests that directly or indirectly exercise module discovery.

## Technical Context

**Language/Version**: Python 3.15 prerelease, while retaining compatibility with Python 3.10 through 3.14

**Primary Dependencies**: Scrapy runtime dependencies, Twisted, lxml, tox, tox-uv, GitHub Actions, `actions/setup-python`

**Storage**: N/A

**Testing**: pytest through tox; targeted module-walker tests and consumer tests for command and spider discovery

**Target Platform**: Linux CI runner; platform exclusions remain explicit while dependency support is incomplete

**Project Type**: Python library and CLI

**Performance Goals**: Module discovery time and behavior must not regress materially; CI latency is acceptable when prerelease coverage is isolated to constrained matrix entries

**Constraints**: Python 3.15 is prerelease; CI must request prereleases explicitly; minimum supported Python compatibility must be preserved; no test or project-code changes are part of this planning-only execution

**Scale/Scope**: One compatibility-sensitive function, its direct and indirect consumers, CI matrix configuration, package metadata, and targeted tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository constitution is still the unratified template, so there are no enforceable project-specific gates. Standard gates for this plan are:

- Preserve backward compatibility for Python 3.10 through 3.14.
- Keep compatibility changes narrowly scoped to observed Python 3.15 behavior.
- Do not remove or weaken existing CI coverage.
- Treat prerelease dependencies and interpreter availability as explicit constraints.

**Gate result**: PASS. No constitutional violations or unresolved planning clarifications.

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
└── detection-draft.json
```

### Source Code (repository root)

```text
.github/workflows/
├── checks.yml
├── tests-macos.yml
├── tests-ubuntu.yml
├── tests-vcs-deps.yml
└── tests-windows.yml

scrapy/
└── utils/
    └── misc.py

tests/
├── test_commands.py
├── test_spiderloader/
│   └── __init__.py
└── test_utils_misc/
    ├── __init__.py
    └── test_walk_modules/

pyproject.toml
tox.ini
```

**Structure Decision**: Keep the library structure unchanged. Limit production edits to CI configuration, package metadata when appropriate, and `scrapy/utils/misc.py`. Add or update focused tests in the existing `tests/test_utils_misc/` layout and use existing consumer suites for regression coverage.

## Complexity Tracking

No constitution violations require justification.
