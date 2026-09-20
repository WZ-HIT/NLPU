# Quickstart Validation: Typed Spider Test Modules

Validation guide for the annotation-only change. Commands are listed for the maintainer to run;
this planning phase does not execute them.

## Prerequisites

- Repository checkout at/after base commit `06af687662112027b4482d31e2714a3cf280a91f`.
- The project's test dependencies installed (pytest with the configured asyncio reactor, Twisted,
  and the static-analysis/lint tools from the project's development requirements).

## Scenario 1 — strict static analysis covers the in-scope modules (SC-001, FR-003)

1. Remove the in-scope spider entries from the per-module untyped-definition exclusion block in
   `pyproject.toml`.
2. Run the project's static type check over the repository.
3. Expect: zero errors for the in-scope modules; every function/method there carries parameter and
   return annotations except explicitly suppressed cases.

## Scenario 2 — behaviour unchanged (SC-003, FR-007)

1. Record the collected test identifiers and outcomes for the in-scope modules before the change.
2. Apply the annotations.
3. Re-run the same modules (see `plan.md` for the in-scope file list) and compare.
4. Expect: identical identifiers and identical pass/fail/skip outcomes.

## Scenario 3 — style and diff hygiene (FR-005, SC-004)

1. Run the project's linting/formatting checks over the changed files.
2. Inspect the diff of the in-scope modules.
3. Expect: only annotations, typing-only imports, and exclusion-list bookkeeping changed.

## Scenario 4 — detect-phase artifact (detect output)

1. Inspect `specs/detection-draft.json`.
2. Validate it against `contracts/detection-draft.schema.json`.
3. Expect: a single top-level `candidates` array whose entries each carry `path`, `symbols`, and
   `reason`, with repository-relative test paths.

## Expected outcomes

| Scenario | Expected result |
|----------|-----------------|
| 1 | Static analysis succeeds with the in-scope exclusions removed |
| 2 | Collected tests and outcomes identical before/after |
| 3 | Diff contains annotations/imports/bookkeeping only |
| 4 | Valid detection draft with repository-relative test paths |
