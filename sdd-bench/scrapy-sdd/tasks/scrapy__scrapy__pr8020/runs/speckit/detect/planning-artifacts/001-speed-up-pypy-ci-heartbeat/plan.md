# Implementation Plan: Speed up PyPy CI and heartbeat waits

**Branch**: `001-speed-up-pypy-ci-heartbeat` | **Date**: 2026-09-20 | **Spec**: [spec.md](spec.md)

**Input**: Scrapy pull request 8020.

## Summary

Reduce PyPy CI time by disabling subprocess coverage under the PyPy extra-dependencies job, and reduce test latency by shortening or bypassing waits for the production engine heartbeat in tests. No production engine behavior changes are planned.

## Technical Context

**Language/Version**: Python 3.10-3.14 and PyPy 3.11

**Primary Dependencies**: pytest, pytest-cov, coverage.py, tox, GitHub Actions

**Storage**: N/A

**Testing**: pytest with coverage configuration; tests must not be run during this planning task

**Target Platform**: Linux CI, with PyPy-specific behavior

**Project Type**: Python library/test infrastructure

**Performance Goals**: Reduce PyPy subprocess startup and heartbeat wait time

**Constraints**: Do not change production heartbeat behavior; preserve useful coverage

**Scale/Scope**: One CI job, one coverage configuration path, and a small set of timing-sensitive tests

## Constitution Check

The repository constitution is still a template, so there are no active project-specific gates. The plan preserves production behavior and limits changes to CI/test support.

## Project Structure

### Documentation

```text
specs/001-speed-up-pypy-ci-heartbeat/
├── spec.md
├── plan.md
├── tasks.md
└── detection-draft.json
```

### Repository Touchpoints

```text
.github/workflows/tests-ubuntu.yml
tox.ini
pyproject.toml
tests/test_engine.py
tests/test_engine_close_spider.py
tests/test_engine_loop.py
tests/test_command_shell.py
tests/test_crawler_subprocess.py
```

**Structure Decision**: Keep changes in the existing Scrapy root layout, using the current CI, tox, and pytest test files.

## Complexity Tracking

No constitution violations or new components are required.
