## Purpose

Keep the project's static type-checking contract consistent across every test
module, including test function bodies that were previously exempt.

## ADDED Requirements

### Requirement: All test modules are checked with untyped definitions enabled

The project SHALL run mypy over `tests` with `check_untyped_defs` enabled for
every test module, without per-module exemptions for the modules covered by
this change.

#### Scenario: Remaining test modules are checked

- **WHEN** the configured mypy check runs over the test suite
- **THEN** the modules covered by this change are checked with
  `check_untyped_defs` enabled and no per-module opt-out remains

#### Scenario: Test behavior is preserved

- **WHEN** the affected test modules are collected and run
- **THEN** they exercise the same behavior and pass as before the typing change
