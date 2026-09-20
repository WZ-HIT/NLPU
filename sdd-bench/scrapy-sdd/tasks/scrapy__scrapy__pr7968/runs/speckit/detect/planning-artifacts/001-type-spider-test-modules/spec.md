# Feature Specification: Typed Spider Test Modules

**Feature Branch**: `001-type-spider-test-modules`

**Created**: 2026-09-20

**Status**: Draft

**Input**: PR task: `scrapy/scrapy` #7968, "Type spider-related test modules", base commit `06af687662112027b4482d31e2714a3cf280a91f`

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Static analysis covers spider test code (Priority: P1)

A Scrapy maintainer reviews the spider-related test modules (spider, crawl-spider, sitemap-spider,
spider-middleware output-chain/process-start, and the shared spider test helpers) and finds that
their function signatures, fixtures, and helper classes carry explicit parameter and return types,
so the project's strict static analysis pass checks the *bodies* of those functions instead of
silently skipping them.

**Why this priority**: This is the entire purpose of the pull request. Without annotations the
modules stay on the static-analysis exclusion list, so type errors introduced by future edits are
invisible until runtime.

**Independent Test**: Run the project's type checker over the repository with no per-module
exclusion for the spider-related test modules and confirm it reports zero errors, i.e. the modules
no longer need their "untyped-definition" exclusion entry.

**Acceptance Scenarios**:

1. **Given** the spider-related test modules listed in the change, **When** the repository's strict
   static type check runs, **Then** no type errors are reported for those modules and each
   function/method definition has explicit parameter and return annotations.
2. **Given** a spider-related test module previously excluded from body checking, **When** the
   change is applied, **Then** the module is no longer listed in the per-module exclusion block.
3. **Given** an annotation that would be wrong (e.g. the wrong response type for a fixture),
   **When** static analysis runs, **Then** the mismatch is reported as an error rather than being
   skipped.

---

### User Story 2 - Behaviour is unchanged for test execution (Priority: P2)

A contributor runs the spider-related test modules after the annotation pass and observes exactly
the same tests executing with the same results, including tests that were previously skipped or
expected to fail.

**Why this priority**: Annotations must be documentation and checking metadata only; any change in
runtime behaviour would silently invalidate the regression signal the tests provide.

**Independent Test**: Execute the affected test modules before and after the change and compare the
collected test identifiers and pass/fail/skip outcomes.

**Acceptance Scenarios**:

1. **Given** the annotated modules, **When** the affected test modules are executed, **Then** the set
   of collected test identifiers and their outcomes is identical to the unannotated baseline.
2. **Given** a helper class or fixture in the affected modules, **When** it is annotated, **Then** its
   runtime contract (accepted arguments, yielded/returned values) is unchanged.

---

### User Story 3 - Reviewable, low-risk annotation-only diff (Priority: P3)

A reviewer inspects the diff and can confirm at a glance that only annotations, imports needed by
those annotations, and exclusion-list bookkeeping changed — no assertion, helper logic, or test
orchestration was rewritten.

**Why this priority**: Keeps the change trivially revertible and avoids hiding behaviour changes
inside a large "typing" pull request.

**Independent Test**: Inspect the diff of the affected modules and verify every changed line is an
annotation, a typing-only import, or an exclusion-list entry.

**Acceptance Scenarios**:

1. **Given** the change, **When** the diff is reviewed, **Then** runtime statements (assertions,
   control flow, fixtures' bodies) are unmodified except where an annotation required a
   typing-only import.
2. **Given** a module that already satisfied static analysis without annotations, **When** the change
   is applied, **Then** its behaviour is untouched and its annotations are the only additions.

---

### Edge Cases

- Tests that intentionally exercise invalid calls (e.g. passing a response object where a request is
  expected) need a narrow, documented suppression rather than a widened annotation.
- Dynamically built spider classes, monkeypatched callables, and Twisted `Deferred`-returning
  fixtures cannot express a single precise type; the annotation must describe the most accurate
  supported type and record any residual suppression inline.
- Spider middleware tests mix synchronous and asynchronous spider callbacks; annotations must cover
  both without narrowing the accepted callback shape.
- Helpers whose subclasses live in other modules must stay overridable with compatible signatures,
  otherwise the type check passes by breaking the extension contract.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every function and method defined in the spider-related test modules in scope MUST have
  explicit parameter and return annotations, except where a documented inline suppression is
  required.
- **FR-002**: The shared spider test helpers in scope (the spider fixtures/classes used by the spider
  test modules and the reusable spider test base class) MUST be annotated consistently with the test
  modules that use them.
- **FR-003**: Project static-analysis configuration MUST no longer exclude any in-scope module from
  untyped-definition body checking.
- **FR-004**: Annotations MUST NOT change runtime behaviour: no assertion, control-flow, fixture, or
  helper body may change semantics as part of this feature.
- **FR-005**: All annotations MUST be expressed in the project's established style (module-level
  postponed-annotation import, built-in generics/union syntax, typing-only imports guarded for
  static analysis) so that linting rules for annotations pass unchanged.
- **FR-006**: Where a precise annotation is impossible, the module MUST use the narrowest accurate
  annotation plus an inline suppression, and the suppression MUST be justified by the surrounding
  code.
- **FR-007**: The set of test identifiers collected from the in-scope modules and their outcomes MUST
  be identical before and after the change.
- **FR-008**: The scope of the change MUST be limited to spider-related test modules and their test
  helpers; unrelated static-analysis exclusions MUST remain in place.

### Key Entities *(include if feature involves data)*

- **In-scope test module**: A test module whose subject is spiders or spider middlewares, together
  with the test-helper modules those tests import (spider fixtures and the shared spider test base
  class).
- **Annotation target**: A function, method, fixture, or attribute in an in-scope module that gains
  explicit parameter/return types or an inline suppression.
- **Static-analysis exclusion entry**: The per-module configuration entry that disables
  untyped-definition body checking for a module; it is removed for each module that becomes fully
  annotated.
- **Detection candidate**: A repository-relative test path that a reviewer (or tooling) should treat
  as relevant to this change, together with the symbols it exercises and the reason it is relevant.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the in-scope modules pass the project's strict static type check with no
  per-module exclusion for untyped-definition body checking.
- **SC-002**: 0 new inline suppression comments are introduced beyond those required by
  intentionally-invalid-call tests, and every introduced suppression is accompanied by an
  explanation in review.
- **SC-003**: The collected test identifiers and outcomes for the in-scope modules are 100% identical
  between the pre-change and post-change runs.
- **SC-004**: A reviewer can classify every changed line in the in-scope modules as annotation,
  typing-only import, or configuration bookkeeping — 0 runtime logic changes.

## Assumptions

- The project's static-analysis configuration (strict mode, per-module exclusion list) stays in
  place; only the entries for the in-scope spider-related modules are removed.
- "Spider-related" covers the spider test modules and the test-helper modules they import, including
  the shared spider test base class and the spider fixture classes.
- Annotations for tests are optimization- and behaviour-neutral; the standard library's postponed
  evaluation of annotations means no runtime cost is added for the test suite.
- Python 3.10+ is the supported baseline, so modern annotation syntax is acceptable.
- No test bodies are refactored to "make typing easier" as part of this feature.
