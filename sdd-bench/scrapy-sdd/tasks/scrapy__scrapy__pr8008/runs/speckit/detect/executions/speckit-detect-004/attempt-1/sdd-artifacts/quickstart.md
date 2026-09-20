# Quickstart Validation: Stabilize Slow-Pipeline Spider-Start Test

## Prerequisites

- Install the repository's test dependencies.
- Use the base revision's supported Python environment.
- Apply the test-only change described in `plan.md`.

## Validation Scenarios

1. Run the focused slow-pipeline test repeatedly and confirm that neither item completion order causes a failure.
2. Run the rest of `tests/test_spider_start.py` and confirm that ordered assertions remain active.
3. Temporarily remove, duplicate, or alter one expected item and confirm that the slow-pipeline assertion fails, then restore the test data.
4. Run the relevant CI matrix entry on Windows or another environment with coarse timer resolution if available.

The implementation phase should use the repository's normal pytest invocation; planning does not execute tests.
