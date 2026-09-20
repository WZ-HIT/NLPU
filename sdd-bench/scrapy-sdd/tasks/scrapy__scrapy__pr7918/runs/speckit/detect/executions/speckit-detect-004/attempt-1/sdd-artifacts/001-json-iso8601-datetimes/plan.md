# Implementation Plan: ISO 8601 Date and Time Serialization in ScrapyJSONEncoder

**Branch**: `001-json-iso8601-datetimes` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-json-iso8601-datetimes/spec.md`

**Note**: This plan is produced by the `$speckit-plan` phase of the Detect workflow. It
describes design intent only; no project code or tests are modified in this stage.

## Summary

The project's JSON encoder currently formats temporal values with fixed `strftime` patterns
(`%Y-%m-%d %H:%M:%S` for `datetime`, `%Y-%m-%d` for `date`, `%H:%M:%S` for `time`), which is
not ISO 8601 and silently drops microseconds and UTC offsets. The change replaces those three
branches with the standard-library ISO 8601 representation of each value, so that every
consumer of the encoder (JSON/JSON Lines item exporters and the periodic log extension)
emits parseable, lossless date/time strings. Everything else the encoder handles keeps its
current behavior.

## Technical Context

**Language/Version**: Python 3.11 (repository metadata requires Python 3.9+; ISO 8601 output
for `datetime` subclasses of interest is available throughout)

**Primary Dependencies**: Python standard library only (`datetime`, `json`); existing runtime
imports in `scrapy/utils/serialize.py` (`itemadapter`, `twisted`, `scrapy.http`) are unchanged

**Storage**: N/A — serialization is in-memory; feeds are written by existing feed-export code

**Testing**: pytest (repository test suite under `tests/`), invoked with the repository's
existing configuration; not executed in this planning stage

**Target Platform**: Any platform supported by the project (pure Python)

**Project Type**: Library / framework (single project layout: package under `scrapy/`, tests
under `tests/`)

**Performance Goals**: No measurable change. The replacement is a single method call per
temporal value, comparable in cost to the previous `strftime` call.

**Constraints**: Preserve the encoder's public import path and constructor behavior; add no
runtime dependency; do not alter serialization of non-temporal types.

**Scale/Scope**: One source module with a three-branch change; two indirect consumers with no
code change; a small number of test expectations that assert the previous text format.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution at `/workspace/.specify/memory/constitution.md` is still the
unfilled core template (placeholder principle names and descriptions, no ratification
metadata). No project-specific ratcheted principles are available to gate this feature, so
the standard gates below are applied and recorded for traceability:

| Gate | Status | Evidence |
|------|--------|----------|
| Public interface stability | PASS | Class name, module path, and constructor keyword pass-through are unchanged (FR-009, FR-010). |
| No new dependencies | PASS | Only the standard library is used (FR-009). |
| Scope discipline / YAGNI | PASS | The change is confined to the JSON encoder's temporal branches (FR-001–FR-003); no other exporter is touched. |
| Backward-compatibility transparency | PASS | The format change is the requested behavior; it is documented and covered by updated expectations (FR-007, FR-008, SC-005). |
| Testability | PASS | Every requirement maps to a directly observable serialized string (SC-001–SC-005). |

No violations, so the Complexity Tracking section is not required.

## Project Structure

### Documentation (this feature)

```text
specs/001-json-iso8601-datetimes/
├── plan.md              # This file ($speckit-plan command output)
├── research.md          # Phase 0 output ($speckit-plan command)
├── data-model.md        # Phase 1 output ($speckit-plan command)
├── quickstart.md        # Phase 1 output ($speckit-plan command)
├── contracts/           # Phase 1 output ($speckit-plan command)
├── checklists/
│   └── requirements.md  # Spec quality checklist ($speckit-specify command)
├── spec.md              # Feature specification ($speckit-specify command)
└── tasks.md             # Phase 2 output ($speckit-tasks command)
```

### Source Code (repository root)

```text
scrapy/
├── utils/
│   └── serialize.py             # ScrapyJSONEncoder.default — the only production change
├── exporters.py                 # JsonItemExporter / JsonLinesItemExporter (consumers, unchanged)
└── extensions/
    └── periodic_log.py          # PeriodicLog (consumer, unchanged)

tests/
├── test_utils_serialize.py      # Direct encoder tests; asserts exact temporal strings
├── test_exporters.py            # JSON/JSON Lines exporter tests; assert exported temporal strings
└── test_extension_periodic_log.py  # Periodic log JSON output (same serialization path)
```

**Structure Decision**: Single-project library layout. The implementation is confined to
`scrapy/utils/serialize.py`; `scrapy/exporters.py` and `scrapy/extensions/periodic_log.py`
are documented as affected consumers but require no code change because they delegate to the
encoder.

## Design sketch (intent only)

The date/time branches of the encoder's `default` method change from fixed-format formatting
to the standard-library ISO 8601 representation of the value:

| Branch | Before | After |
|--------|--------|-------|
| `datetime` | `strftime("%Y-%m-%d %H:%M:%S")` | ISO 8601 date-time |
| `date` | `strftime("%Y-%m-%d")` | ISO 8601 calendar date |
| `time` | `strftime("%H:%M:%S")` | ISO 8601 clock time |

The `DATE_FORMAT` / `TIME_FORMAT` class attributes are no longer needed to produce temporal
output and should not be left behind as misleading configuration surface (FR-010). Branch
ordering is preserved so `datetime` never falls into the `date` branch.

## Complexity Tracking

Not applicable — the Constitution Check reports no violations.
