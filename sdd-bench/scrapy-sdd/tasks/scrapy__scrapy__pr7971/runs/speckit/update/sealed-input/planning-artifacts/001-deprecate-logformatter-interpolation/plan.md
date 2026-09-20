# Implementation Plan: Deprecate Log Formatter Message Interpolation With the Returned Dict

**Branch**: `001-deprecate-logformatter-interpolation` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-deprecate-logformatter-interpolation/spec.md`

## Summary

Restore backward compatibility for custom `LogFormatter` results that omit
`args` and expect the message to be interpolated with the returned dictionary,
while emitting a deprecation warning that directs maintainers to pass an
explicit `args` value. The documented mapping/tuple `args` paths and their
logging behavior stay unchanged.

## Technical Context

**Language/Version**: Python 3.9+ (project supports 3.9 through 3.14)

**Primary Dependencies**: Twisted, stdlib `logging`; no new dependency

**Storage**: N/A

**Testing**: pytest (tests must NOT be run in this planning stage)

**Target Platform**: Cross-platform Python library

**Project Type**: Single library (`scrapy/`) with a pytest suite (`tests/`)

**Performance Goals**: No measurable change; adapter does one dictionary
membership/default lookup per log record

**Constraints**: Must not break the existing tuple/mapping `args` contract; the
warning must fire at most once per adapted legacy result

**Scale/Scope**: One helper function in `scrapy/utils/log.py` plus tests and
release documentation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution file is an unfilled template, so there are no ratified
gates to enforce. The work follows the repository's existing conventions:
backward compatibility is preserved during deprecation, behavior is covered by
focused unit tests, and the public contract is documented.

**Post-design re-check**: PASS — the design adds a warning path in the existing
adapter without changing the formatter result shape, changing callers, or adding
dependencies.

## Project Structure

### Documentation (this feature)

```text
specs/001-deprecate-logformatter-interpolation/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── logformatter-adapter.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
scrapy/
├── logformatter.py          # LogFormatter result contract (unchanged shape)
└── utils/
    └── log.py               # logformatter_adapter, where the deprecation lands

tests/
├── test_utils_log.py        # adapter-specific tests (primary candidate)
└── test_logformatter.py     # formatter result contract tests (secondary candidate)

docs/
└── news.rst                 # release-note entry for the deprecation
```

**Structure Decision**: Single-project layout; the change is confined to the
logging utility and its tests, matching the existing `scrapy/utils/log.py`
adapter boundary.

## Complexity Tracking

No constitution violations; no complexity exceptions requested.
