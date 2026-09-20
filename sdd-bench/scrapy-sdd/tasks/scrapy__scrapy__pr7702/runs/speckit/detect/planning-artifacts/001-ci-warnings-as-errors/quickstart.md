# Quickstart: CI Warnings as Errors

## Prerequisites

- Install the project's test dependencies using the normal tox environment.
- Do not modify product behavior; this is a test-policy change.

## Validation scenarios

1. Run a focused test that emits an unexpected warning and confirm pytest
   reports an error.
2. Run a focused test using `pytest.warns` for an intentional warning and
   confirm it passes.
3. Run each affected warning-sensitive test module listed in
   `detection-draft.json` and confirm failures are limited to unhandled
   warnings.
4. Run the supported tox environments to detect version-specific warnings.

## Expected outcomes

- Unexpected warnings fail at the point they are emitted.
- Intentional warnings remain observable and explicitly asserted.
- Suppressions are narrow and documented.
