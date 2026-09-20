# Requirements Document

## Introduction

This spec covers the cc-sdd Detect planning phases for `scrapy/scrapy` PR #7968,
"Type spider-related test modules". The deliverable of the Detect stage is a
detection draft that names the candidate test files for the PR, the symbols inside
them, and the evidence-based reason each file is a candidate. The PR itself adds
type annotations to spider-related test modules; this spec does not implement that
work.

## Boundary Context

- **In scope**: locating candidate test files for PR #7968; recording candidates,
  symbols, and reasons in the mounted planning directory.
- **Out of scope**: editing `tests/`, editing `scrapy/`, editing `pyproject.toml`,
  running pytest/tox/mypy, producing the final detection verdict.
- **Adjacent expectations**: later cc-sdd phases consume `detection-draft.json` and
  are responsible for pruning and verifying candidates.

## Requirements

### Requirement 1: Candidate detection draft

**Objective:** As an SDD detect agent, I want a machine-readable draft of candidate
test files, so that later stages can verify which test modules the PR touches.

#### Acceptance Criteria

1. The detect stage shall write exactly one `detection-draft.json` file inside the
   mounted planning directory.
2. The `detection-draft.json` document shall contain only a `candidates` array.
3. Each candidate shall contain `path`, `symbols`, and `reason`.
4. Each candidate `path` shall be a repository-relative test path.

### Requirement 2: Evidence-based candidate selection

**Objective:** As a reviewer, I want each candidate grounded in repository
evidence, so that the draft can be audited without re-deriving the reasoning.

#### Acceptance Criteria

1. When a spider-related test module is listed in the `pyproject.toml` mypy backlog
   override, the draft shall include that module's test path.
2. When a candidate is included on weaker evidence, the draft shall state that
   weaker confidence and its rationale in the candidate `reason`.
3. The draft shall record the spider-focused symbols (test classes, test methods,
   and spider helpers) present in each candidate file.

### Requirement 3: Read-only preservation of the repository

**Objective:** As a project maintainer, I want planning to stay out of the code
tree, so that no source or test file changes during the Detect stage.

#### Acceptance Criteria

1. The detect stage shall not modify any file under `scrapy/`, `tests/`,
   `tests_typing/`, or the repository configuration.
2. The detect stage shall not execute tests or type-checking commands.
3. While the workspace is mounted read-only, the detect stage shall write only
   inside the mounted planning directory (`/workspace/.kiro/specs`).
