# Brief: Type spider-related test modules (scrapy/scrapy PR #7968)

## Problem

`scrapy/scrapy` at base commit `06af687662112027b4482d31e2714a3cf280a91f` keeps a set of
test modules outside full mypy checking. `pyproject.toml` carries a `# TODO`
override (`[[tool.mypy.overrides]]`, modules list ending at line 143) whose entries
set `check_untyped_defs = false`, i.e. those test modules are not yet annotated.
PR #7968 ("Type spider-related test modules") is the slice of that backlog that
covers spider-related test modules.

## Approach

1. Establish, from repository evidence, which test modules are spider-related and
   still un-annotated (the mypy backlog list is the authoritative marker).
2. Record the resulting candidate test files, their key symbols, and the reason
   each one is a candidate in `detection-draft.json`.
3. Hand the draft to the next cc-sdd phase for verification. No production code
   and no test file may be modified by this stage.

## Scope

- In scope: locating candidate test files for PR #7968 and writing the planning
  artifacts for the detection stage.
- Out of scope: applying type annotations, editing `pyproject.toml`, editing any
  test under `tests/`, running tests or static analysis.

## Constraints

- The workspace is mounted read-only; only the mounted planning directory
  (`/workspace/.kiro/specs`) is writable.
- Detection artifacts must live only in the mounted planning directory.
- `detection-draft.json` must contain a single `candidates` array whose entries
  have `path`, `symbols`, and `reason`; all `path` values are repository-relative
  test paths.

## Evidence used

- `pyproject.toml` `[[tool.mypy.overrides]]` "TODO" module list (base commit).
- File contents of the spider-related test modules under `tests/`.
- `tests_typing/test_spiders.mypy-testing` and `tox.ini` (`mypy`, `mypy-tests`
  environments) for context on the typing workflow.
