# Design Document

## Overview

**Purpose**: This feature delivers the Detect-stage planning artifacts for
`scrapy/scrapy` PR #7968.
**Users**: cc-sdd downstream phases (validation, implementation planning) read the
draft to know which test modules are in scope.
**Impact**: No repository change; artifacts land only in the mounted planning
directory.

### Goals

- Produce one well-formed `detection-draft.json` with a `candidates` array.
- Rank candidates by evidence strength and state that strength in `reason`.

### Non-Goals

- Applying annotations, editing `pyproject.toml`, or running the test suite.
- Deciding the final detection verdict.

## Boundary Commitments

### This Spec Owns

- The `detection-draft.json` document and its candidate list.
- The spec-phase artifacts (`brief.md`, `spec.json`, `requirements.md`,
  `design.md`, `tasks.md`) in the planning directory.

### Out of Boundary

- Any edit under `tests/`, `tests_typing/`, `scrapy/`, or `pyproject.toml`.
- Candidate verification runs (pytest/mypy/tox) by later phases.

### Allowed Dependencies

- Read-only access to the repository at base commit `06af687`.

### Revalidation Triggers

- The PR's changed-file set becomes available: re-prune the candidate list.
- The mypy backlog override list changes: re-derive high-confidence candidates.

## Detection Strategy

Two evidence sources drive the candidate list, in descending strength:

1. **Mypy backlog override (high confidence).** `pyproject.toml` keeps a `# TODO`
   module list with `check_untyped_defs = false`. Spider-named entries in that list
   are the modules that still need annotations, so a "Type spider-related test
   modules" change is expected to touch them:
   `tests.spiders`, `tests.test_spider`, `tests.test_spider_crawl`,
   `tests.test_spider_sitemap`, `tests.test_spidermiddleware_output_chain`,
   `tests.test_spidermiddleware_process_start`, `tests.utils.bases.spider` — plus
   the spider-named `tests.test_closespider` entry.
2. **Spider-topic test modules (medium confidence).** Test modules whose subject is
   spiders/spider loading/spider state but which are absent from the backlog:
   `tests/test_spiderloader/__init__.py`, `tests/test_utils_spider.py`,
   `tests/test_spiderstate.py`, `tests/test_spider_start.py`. These are scoped in by
   topic and are plausible members of the same typing sweep.

### Candidate Inventory (12 files)

| # | Path (repository-relative) | Evidence tier |
|---|----------------------------|---------------|
| 1 | `tests/test_spider.py` | Mypy backlog |
| 2 | `tests/test_spider_crawl.py` | Mypy backlog |
| 3 | `tests/test_spider_sitemap.py` | Mypy backlog |
| 4 | `tests/test_spidermiddleware_output_chain.py` | Mypy backlog |
| 5 | `tests/test_spidermiddleware_process_start.py` | Mypy backlog |
| 6 | `tests/spiders.py` | Mypy backlog |
| 7 | `tests/utils/bases/spider.py` | Mypy backlog |
| 8 | `tests/test_closespider.py` | Mypy backlog (extension-scoped) |
| 9 | `tests/test_spiderloader/__init__.py` | Spider topic |
| 10 | `tests/test_utils_spider.py` | Spider topic |
| 11 | `tests/test_spiderstate.py` | Spider topic |
| 12 | `tests/test_spider_start.py` | Spider topic |

## File Structure Plan

| Path | Purpose |
|------|---------|
| `/workspace/.kiro/specs/detection-draft.json` | Detection draft: single `candidates` array. |
| `/workspace/.kiro/specs/type-spider-related-test-modules/brief.md` | Discovery brief for the Detect stage. |
| `/workspace/.kiro/specs/type-spider-related-test-modules/spec.json` | Spec metadata (`phase: detect`). |
| `/workspace/.kiro/specs/type-spider-related-test-modules/requirements.md` | Detect-stage requirements (EARS). |
| `/workspace/.kiro/specs/type-spider-related-test-modules/design.md` | This design. |
| `/workspace/.kiro/specs/type-spider-related-test-modules/tasks.md` | Detect-stage task list. |

No file outside the mounted planning directory is created or modified.

## Risks

- The PR diff is not available in this environment (shallow clone at the base
  commit), so confidence tiers are inferred from repository state rather than from
  the change itself. The draft therefore labels medium-confidence entries in their
  `reason` field instead of presenting them as certain.
- `tests.test_closespider` is extension-scoped; it is kept as a medium/high
  boundary candidate because its module name is spider-related and it sits in the
  same mypy backlog.
