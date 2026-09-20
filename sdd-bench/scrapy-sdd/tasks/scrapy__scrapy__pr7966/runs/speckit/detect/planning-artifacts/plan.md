# Implementation Plan: Address VCS workflow warnings

**Spec**: `specs/spec.md`

## Summary

Triage the warnings produced by the scheduled `vcs-deps` workflow, classify each as Scrapy-origin or dependency-origin, and apply the narrowest handling that keeps the run actionable.

## Technical Context

**Language/Version**: Python 3.10-3.14 (the workflow runs 3.14)

**Primary Dependencies**: tox, tox-uv, uv, Twisted, pyOpenSSL, cryptography, service-identity, lxml, parsel, w3lib, httpx2, h2, brotli/zstandard, uvloop

**Testing**: pytest with warning filters and `pytest.mark.filterwarnings`

**Target Platform**: GitHub Actions Ubuntu runner

**Project Type**: Library/CLI

**Constraints**: Do not weaken warning visibility; preserve development-branch coverage

**Scale/Scope**: One scheduled workflow, its tox environment, and the warning-sensitive tests it exercises

## Constitution Check

`.specify/memory/constitution.md` is an unfilled template, so no project-specific gates apply. The plan preserves existing tests and limits changes to warning handling.

## Project Structure

```text
.github/workflows/tests-vcs-deps.yml
tox.ini
pyproject.toml
scrapy/
tests/
tests/utils/bases/
```

**Structure Decision**: Reuse the existing single-project layout; no new packages or test modules are expected.

## Phase 0: Research

See `specs/research.md`: classify warning sources (`pyproject.toml` filters, per-test `filterwarnings` markers, `scrapy/utils/_deps_compat.py` version gates) and select the narrowest handling.

## Phase 1: Design

See `specs/data-model.md` for the warning/candidate records and `specs/contracts/README.md` for the detection artifact contract.

## Complexity Tracking

No constitution violations.
