# Implementation Plan: Fix open_in_browser ReDoS Test Flakiness and a Broken Exploit Input

**Branch**: `001-fix-redos-test-flakiness` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-fix-redos-test-flakiness/spec.md`

## Summary

The `open_in_browser` ReDoS regression tests currently prove "no catastrophic
backtracking" by timing a call over a very large crafted body against a small
CPU budget, and at least one crafted body terminates the removed pattern early
instead of attacking it. This plan makes the regression criteria deterministic
(independent of machine speed) and makes each exploit body genuinely expensive
for the pattern it targets, while keeping the shipped `open_in_browser`
behavior and every existing assertion intact.

The technical approach is test-only: derive the pass/fail decision from a
detection signal that is stable across machines rather than from an absolute
time budget, and validate every exploit body against the pattern it claims to
attack before accepting it. Product code is touched only if that validation
uncovers a real defect in base-tag injection.

## Technical Context

**Language/Version**: Python >= 3.10 (repository `requires-python`; minimum tox environment is 3.10)

**Primary Dependencies**: Scrapy itself (`scrapy.http.HtmlResponse`/`TextResponse`, `scrapy.utils.response.open_in_browser`) and, for the tests, `pytest` with the repository's configured `--reactor=asyncio` option

**Storage**: N/A — the viewer writes a temporary file under the system temp directory only

**Testing**: `pytest`; primary module `tests/test_utils_response.py`, end-to-end touch point `tests/test_commands.py` (`TestViewCommand`) using a generated fake browser script

**Target Platform**: Linux, macOS, and Windows CI workers (the existing `view`-command test is already POSIX-gated)

**Project Type**: single project — library (`scrapy/`) with tests at the repository root (`tests/`)

**Performance Goals**: Each exploit body must cost at least two orders of magnitude more under the removed pattern than under the shipped implementation; with the shipped implementation, the regression assertions must complete far inside their budget even on slow or CPU-contended workers.

**Constraints**: No network access, no real browser, no new runtime dependency, no public API change; the change stays inside the test suite unless a genuine product defect is found (FR-008).

**Scale/Scope**: One test module carries the regression tests (2 ReDoS tests plus one shared helper) with one additional module used as end-to-end verification.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` in this repository still contains the
unratified template (placeholder principle names and descriptions), so there
are no project-specific gates to enforce. The plan therefore applies the
generic gates that the template implies, and records them here explicitly:

- **No unnecessary dependencies**: the change introduces no new runtime or test
  dependency. PASS.
- **No public interface change**: no signature, behavior, or documented
  guarantee of `scrapy.utils.response.open_in_browser` changes. PASS.
- **Deterministic, independently testable increments**: User Story 1 is
  verifiable by re-running the module and by reinstating a vulnerable pattern in
  a scratch harness; User Story 2 by measuring the removed pattern against each
  body; User Story 3 by the pre-existing viewer assertions. PASS.
- **Scope discipline**: product code is changed only if exploit validation
  exposes a real defect, and such a change requires its own test. PASS.

**Post-Phase-1 re-check**: PASS — the design introduces no dependencies, no
interface changes, and no new production code paths.

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-redos-test-flakiness/
├── plan.md              # This file ($speckit-plan command output)
├── research.md          # Phase 0 output ($speckit-plan command)
├── data-model.md        # Phase 1 output ($speckit-plan command)
├── quickstart.md        # Phase 1 output ($speckit-plan command)
├── contracts/           # Phase 1 output ($speckit-plan command)
│   └── redos-regression-contract.md
├── checklists/
│   └── requirements.md  # Specification quality checklist
├── spec.md              # Feature specification ($speckit-specify command output)
└── tasks.md             # Phase 2 output ($speckit-tasks command)
```

### Source Code (repository root)

```text
scrapy/
├── commands/
│   └── view.py                 # `scrapy view` entry point that calls open_in_browser
├── shell.py                    # exposes `view` in the shell namespace
└── utils/
    └── response.py             # open_in_browser implementation (regex-free base-tag injection)

tests/
├── test_utils_response.py      # PRIMARY: open_in_browser unit + ReDoS regression tests
├── test_commands.py            # `view` command end-to-end tests (TestViewCommand)
└── utils/
    └── cmdline.py              # helpers used by the command tests (recording browser script)
```

**Structure Decision**: Single-project layout. The implementation lives in
`scrapy/utils/response.py` and the tests that define correctness live under
`tests/`. This feature is expected to change `tests/test_utils_response.py`
only; `tests/test_commands.py` remains the end-to-end verification surface
because `TestViewCommand` is the only test that exercises the full
`scrapy view` → `open_in_browser` → browser-command path.

## Complexity Tracking

No constitution violations; this table is intentionally empty.
