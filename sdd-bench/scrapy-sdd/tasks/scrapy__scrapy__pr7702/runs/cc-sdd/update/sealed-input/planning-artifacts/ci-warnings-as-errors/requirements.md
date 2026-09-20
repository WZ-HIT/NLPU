# Requirements: CI warnings to errors

Source: `/task-input/task.md` — scrapy/scrapy PR 7702, base commit `c7eacdbb30a4563bbbe04ed02781768f4e19eabb`, "CI: warnings → errors", fixes #7262.

## Scope (planning only)

This spec covers the Detect planning phases only (spec, detect). No project code or test code is modified, and no tests are executed.

## Context

The change enables Python warnings as errors for the whole test suite instead of only for "latest" dependency environments. When the pytest warning filters in `pyproject.toml` (currently `[tool.pytest.ini_options].filterwarnings`, three entries) begin with `error`, every warning raised during collection or execution fails the test unless it is explicitly expected or ignored.

## Requirements

- R1: The suite must run with warnings escalated to errors globally rather than per-environment.
- R2: Intentional Scrapy deprecation warnings raised by tests must remain assertable (via `pytest.warns`, `recwarn`, or scoped `warnings.catch_warnings`), so legitimate deprecation coverage is preserved.
- R3: Third-party warnings that cannot be fixed in this repository must be ignored narrowly (message- and module-scoped filters), not silenced globally.
- R4: Any behaviour change must be observable through the existing test suite; no test may be deleted merely to avoid a warning.

## Acceptance criteria

- AC1: `pyproject.toml` warning configuration escalates warnings to errors for the default test run.
- AC2: Every test that intentionally triggers a `ScrapyDeprecationWarning` (or another warning) declares the expectation explicitly instead of relying on warnings being non-fatal.
- AC3: Tests whose failure output changes only because a warning became an error are updated in the same change.

## Out of scope

- Implementation of the fix (only candidate detection is produced here).
- Running the test suite or installing dependencies.
