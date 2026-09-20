## Context

`tool.mypy` is configured with `strict = true`, while `tests.*` overrides allow
untyped and incomplete definitions. A remaining override disables
`check_untyped_defs` for 14 test modules. The test modules use pytest fixtures,
Twisted Deferreds, and mocks, so annotations must fit those existing helpers
rather than replace test behavior. See `proposal.md` for the motivation.

## Goals / Non-Goals

**Goals:**

- Make mypy check the bodies of the remaining test functions.
- Use the smallest accurate annotations and existing test utilities.
- Remove the now-unneeded configuration override.

**Non-Goals:**

- Changing runtime behavior, public APIs, or production type annotations.
- Refactoring test structure merely to simplify annotations.
- Enabling `disallow_untyped_defs` for the test suite beyond the existing
  project-wide mypy policy.

## Decisions

- Annotate fixture parameters, helper functions, and non-trivial local values
  where mypy needs the information, preferring precise project types over
  `Any`.
- Keep `allow_untyped_defs` and `allow_incomplete_defs` in the general
  `tests.*` override; this change only removes the `check_untyped_defs = false`
  exception. Alternative: enable full strictness for tests, which is broader
  than the requested change.
- Fix type errors at the test boundary with existing pytest, Twisted, and
  Scrapy helpers. Alternative: suppress errors with ignores, which would leave
  the checked coverage ineffective.

## Risks / Trade-offs

- Fixture typing can become overly concrete and break when test helpers evolve
  → use existing protocol/helper types and keep annotations local.
- Small annotation edits can accidentally affect collection or parametrization
  → run the affected modules individually and then the mypy test check.
- Removing the override may reveal errors in helper modules not listed as
  candidates → resolve errors in any file under the checked test package while
  keeping the scope limited to typing.
