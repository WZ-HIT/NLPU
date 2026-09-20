# Implementation Plan

## Detect Stage Tasks

- [x] 1. Inspect the task input and repository metadata for PR #7968.
  - Read `/task-input/task.md` (repository, PR number, base commit, title).
  - Confirm the workspace is read-only and identify the mounted planning
    directory (`/workspace/.kiro/specs`).
  - _Requirements: 3.1, 3.3_

- [x] 2. Derive candidate test files from repository evidence.
  - Read the `[[tool.mypy.overrides]]` "TODO" module list in `pyproject.toml`.
  - Enumerate spider-related test modules under `tests/` and cross-check them
    against the backlog list.
  - _Requirements: 2.1, 2.2_

- [x] 3. Collect spider-focused symbols per candidate.
  - Record top-level test classes, test functions, and spider helper classes for
    each candidate path.
  - _Requirements: 2.3_

- [x] 4. Write the detection draft.
  - Write `/workspace/.kiro/specs/detection-draft.json` containing only a
    `candidates` array with `path`, `symbols`, and `reason` per candidate.
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 5. Write the spec-phase planning artifacts in the planning directory.
  - Write `brief.md`, `spec.json`, `requirements.md`, `design.md`, and `tasks.md`
    under `/workspace/.kiro/specs/type-spider-related-test-modules/`.
  - _Requirements: 3.3_

## Deferred (not part of this stage)

- [ ] 6.* Verify the candidate list against the PR's changed-file set once a
  detection-verification phase has that information.
  - Requires the PR diff or a test-selection run; out of scope here.
  - _Requirements: 2.2_
