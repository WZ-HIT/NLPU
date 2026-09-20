# Implementation Plan: Bootstrap Error Exit Codes

**Branch**: `001-bootstrap-error-exit-codes` | **Date**: 2026-09-20 | **Spec**:
[spec.md](spec.md)

## Summary

Align `check`, `parse`, and `fetch` with `crawl` and `runspider` by setting the command
exit code to `1` after crawler processing when bootstrap failed.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Scrapy command framework and crawler process

**Testing**: Existing pytest command integration suites

**Target Platform**: Cross-platform command-line environment

**Project Type**: Python library and CLI

**Constraints**: Do not alter successful or usage-error exit-code behavior.

## Constitution Check

The project constitution is an unfilled template and defines no additional gates for this
change.

## Phase 0: Outline & Research

See [research.md](research.md).

## Phase 1: Design & Contracts

The observable contract is unchanged except for exit status after failed bootstrap. See
[data-model.md](data-model.md), [contracts/command-exit-codes.md](contracts/command-exit-codes.md),
and [quickstart.md](quickstart.md).

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
├── detection-draft.json
└── contracts/
    └── command-exit-codes.md
```

### Source Code

```text
scrapy/commands/check.py
scrapy/commands/parse.py
scrapy/commands/fetch.py
tests/test_command_check.py
tests/test_command_parse.py
tests/test_command_fetch.py
```

## Complexity Tracking

No constitution violations.

## Post-Design Constitution Check

No new complexity or governance concerns.
