# Implementation Plan: CI Warnings as Errors

**Branch**: `001-ci-warnings-as-errors` | **Date**: 2026-09-20 | **Spec**: `spec.md`

## Summary

Enable pytest's global warning-to-error policy, then make intentional or
external warnings explicit and narrowly scoped in affected tests. The plan is
limited to planning and test detection; no project or test code is modified.

## Technical Context

**Language/Version**: Python 3.10-3.14, PyPy 3.11

**Primary Dependencies**: pytest, pytest-twisted, tox, Twisted

**Storage**: N/A

**Testing**: pytest and tox, with `filterwarnings` in `pyproject.toml`

**Target Platform**: CI on Linux, macOS, and Windows

**Project Type**: Python library

**Constraints**: Do not run tests in this planning phase; warnings must remain
errors unless an intentional, documented exception exists

**Scale/Scope**: Repository-wide pytest and tox test environments

## Constitution Check

The project constitution is an unfilled template, so there are no concrete
project gates to enforce. The plan preserves the repository convention of
explicit warning assertions and does not alter runtime behavior.

## Project Structure

```text
specs/001-ci-warnings-as-errors/
|-- spec.md
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- tasks.md
`-- checklists/requirements.md
```

### Source Code

```text
pyproject.toml
tox.ini
tests/
```

**Structure Decision**: Reuse the existing single-project pytest layout. The
only production-side setting is pytest configuration; repository tests are the
verification surface.

## Complexity Tracking

No constitution violations or added architectural complexity.
