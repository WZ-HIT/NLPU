# Implementation Plan: Support IDNA-2003-only domains

**Branch**: `support-idna-2003-domains` | **Date**: 2026-09-20 | **Spec**: `spec.md`

**Input**: Feature specification from `spec.md`

## Summary

Install a narrow compatibility shim over Twisted's IDNA helper functions when
Scrapy is imported. The shim should accept IDNA-2003-only names that Twisted's
preferred IDNA-2008 conversion rejects, while preserving existing results for
valid ASCII and internationalized names.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Twisted 26.4, `idna` 3.x, w3lib

**Storage**: N/A

**Testing**: pytest (planning only; tests must not be run during this phase)

**Target Platform**: Cross-platform Python runtime

**Project Type**: Library/framework

**Performance Goals**: No measurable per-request performance regression; helper
conversion remains constant-time outside DNS work.

**Constraints**: Preserve public API; avoid changing request URLs; preserve
invalid-host failures; keep the shim localized and removable.

**Scale/Scope**: One compatibility hook plus focused unit/integration coverage.

## Constitution Check

The project constitution is an unfilled template, so there are no additional
governance gates to enforce. The plan preserves backward compatibility,
isolates the compatibility behavior, and adds no dependency.

*Post-design re-check*: PASS. The design remains a small compatibility layer
with no schema, public API, or dependency change.

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
scrapy/
├── __init__.py                 # likely import-time activation point
└── utils/
    └── url.py                  # URL conversion context

tests/
├── test_utils_url.py
├── test_resolver.py
├── test_http_request.py
├── test_core_downloader.py
├── test_crawl.py
└── test_toplevel.py
```

**Structure Decision**: Keep the compatibility shim in the package
initialization path, close to where Scrapy's public request APIs are exposed,
and verify it through existing URL, resolver, request, TLS, and crawl suites.

## Complexity Tracking

No constitution violations.
