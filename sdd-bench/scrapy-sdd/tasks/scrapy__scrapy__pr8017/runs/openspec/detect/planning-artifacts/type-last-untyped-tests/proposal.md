## Why

The project type-checks the test suite with mypy, but 14 `tests.*` modules still
disable `check_untyped_defs`. Their function bodies can therefore contain type
errors that neither CI nor local checks report, and the remaining exception is
inconsistent with the rest of the test suite.

## What Changes

- Type the remaining `tests.*` modules covered by the
  `check_untyped_defs = false` override.
- Remove that override and its TODO block from `pyproject.toml`.
- Preserve all existing test behavior and collection.
- Verify the affected test modules with the normal mypy and pytest checks.

## Capabilities

### New Capabilities

- `test-type-checking`: consistent static checking of test function bodies
  across the test suite, including the final modules that currently opt out.

### Modified Capabilities

None.

## Impact

The change affects `pyproject.toml` and these test modules:
`tests.test_cmdline`, `tests.test_downloaderslotssettings`,
`tests.test_dupefilters`, `tests.test_extension_statsmailer`,
`tests.test_extension_throttle`, `tests.test_linkextractors`,
`tests.test_logformatter`, `tests.test_mail`, `tests.test_pqueues`,
`tests.test_scheduler_base`, `tests.test_settings`, `tests.test_squeues`,
`tests.test_squeues_request`, and `tests.test_stats`. There are no runtime API,
package, or dependency changes.
