# Implementation Plan: open_in_browser ReDoS Regression Test Hardening

**Branch**: `001-open-in-browser-redos-tests` | **Date**: 2026-09-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from the mounted method planning directory (`spec.md` in the same directory as this plan)

**Note**: This plan was produced by the `speckit.plan` phase and intentionally
stops before implementation. No tests were executed and no project source or
test file was modified while producing it.

## Summary

Harden the ReDoS regression tests for `scrapy.utils.response.open_in_browser`
(PR `scrapy/scrapy#8064`): make the adversarial-input tests deterministic
(no speed-dependent false failures) and make sure the crafted payloads really
drive super-linear backtracking in the historical patterns they claim to target
(one payload is currently considered broken). Existing behaviour coverage of
`open_in_browser` is preserved. The work is test-only: the production
implementation at the base commit already uses a non-backtracking prefix
insertion strategy.

## Technical Context

**Language/Version**: Python >= 3.10 (project `requires-python`); repository targets modern CPython on CI

**Primary Dependencies**: Scrapy, Twisted, parsel/w3lib (already installed in the test environment); standard library `re`, `time`, `tempfile`, `webbrowser`

**Storage**: N/A (tests write one temporary file per `open_in_browser` call, as the function already does)

**Testing**: pytest (`[tool.pytest.ini_options]` in `pyproject.toml`, `python_files = ["test_*.py", "test_*/__init__.py"]`, `addopts = ["--reactor=asyncio"]`); tox is available for the full matrix but is out of scope for this planning phase

**Target Platform**: Linux CI workers (Windows is skipped by existing `skipif` marks where relevant)

**Project Type**: Single project (Python library with CLI commands and a pytest test suite)

**Performance Goals**: Each adversarial test under 200 ms CPU on the reference runner; vulnerable-pattern behaviour must be measurably super-linear (orders of magnitude, not a marginal factor)

**Constraints**: No new dependencies; no network access; no production-code change; tests must not rely on wall-clock sleeps; the whole adversarial suite must stay within the normal per-test timeout

**Scale/Scope**: One test module (`tests/test_utils_response.py`) plus optional indirect verification through `tests/test_commands.py::TestViewCommand`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` in this checkout is still the unratified
template (`[PRINCIPLE_1_NAME]`, `[SECTION_2_NAME]`, ... placeholders), so it
defines no enforceable gates. The applicable gates are therefore taken from the
repository's own metadata and the task constraints:

| Gate | Status | Evidence |
|------|--------|----------|
| Test-only change (no production edits) | PASS | `scrapy/utils/response.py` already avoids the vulnerable patterns at the base commit |
| No new runtime/test dependency | PASS | Standard library and existing pytest stack only |
| No network access required | PASS | Payloads are generated in memory; `file://` output only |
| Test suite remains runnable with project defaults | PASS | Change stays inside existing pytest-collected modules |
| Security coverage preserved | PASS | Existing behaviour tests are kept; adversarial tests are strengthened |

No violations to justify, so Complexity Tracking stays empty.

## Project Structure

### Documentation (this feature)

```text
/workspace/specs/                 # mounted method planning directory for this run
├── spec.md                       # specify phase output
├── plan.md                       # this file (plan phase output)
├── research.md                   # Phase 0 output
├── quickstart.md                 # Phase 1 output
├── tasks.md                      # tasks phase output
└── detection-draft.json          # detect phase output (candidates array only)
```

`data-model.md` and `contracts/` are intentionally not produced: the change
introduces no new data entities beyond in-memory byte payloads, and it adds no
external interface (the `open_in_browser(response, _openfunc=...)` signature is
unchanged). `research.md` records the decisions behind the payloads instead.

### Source Code (repository root)

```text
scrapy/
├── utils/
│   └── response.py               # open_in_browser implementation (unchanged by this work)
└── commands/
    └── view.py                   # `scrapy view` command, calls open_in_browser

tests/
├── test_utils_response.py        # primary: open_in_browser tests incl. ReDoS tests
└── test_commands.py              # indirect: TestViewCommand exercises open_in_browser end to end
```

**Structure Decision**: Single-project layout, unchanged. All planning
artifacts live in the mounted planning directory (`/workspace/specs`) so that no
repository file is touched during planning. Implementation work is confined to
`tests/test_utils_response.py`; the production module and the CLI command are
read-only references for this feature.

## Phase 0: Outline & Research

Unknowns extracted from the Technical Context and spec:

1. Which test files actually exercise `open_in_browser`?
2. What makes the current ReDoS assertions flaky, and what replacement oracle
   is appropriate for a repository that cannot add tooling?
3. Why is the comment payload considered broken, and what payload shape
   provably triggers the historical patterns?
4. Which behaviour assertions must be preserved verbatim?

Findings and decisions are consolidated in [research.md](./research.md).

## Phase 1: Design & Contracts

- Interface contract: no external interface changes; the observable contract
  exercised by tests (temporary file plus `file://` URL to the browser callback)
  stays as documented in `spec.md`.
- Validation guide: [quickstart.md](./quickstart.md) records the commands and
  expected outcomes for verifying the change in the implementation phase. It is
  not executed during this planning phase, per the no-tests constraint.
- Detect phase: [detection-draft.json](./detection-draft.json) lists the
  candidate test files with the symbols and the reason each is considered
  relevant.

## Post-Design Constitution Re-check

Unchanged from the pre-design check: no production edits, no new dependencies,
no interface change, security coverage preserved. No violations.

## Complexity Tracking

No constitution violations; table intentionally empty.
