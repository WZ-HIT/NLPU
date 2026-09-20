## Why

The PyPy CI job spends most of its runtime on coverage instrumentation that is
started inside every subprocess the test suite spawns, and the tests that
depend on the engine slot heartbeat have to wait for the production heartbeat
interval before the engine retries the scheduler. Both make the PyPy job and
the local test suite slower without reporting anything PyPy-specific to
Codecov.

## What Changes

- The PyPy test environments stop measuring coverage inside subprocesses, which
  is responsible for most of the PyPy job slowdown and does not provide
  PyPy-specific information that would not already be reported by the CPython
  coverage jobs.
- Tests that rely on the engine slot heartbeat are no longer bound by the
  production heartbeat interval: they drive the heartbeat deterministically
  (or with a much shorter interval) instead of waiting several seconds per
  retry.
- No runtime behavior changes: public APIs, settings, signals, and crawling
  behavior stay exactly the same.

## Capabilities

### New Capabilities

- `ci-pypy-coverage`: how the PyPy test environments collect coverage, in
  particular whether subprocesses spawned by the test suite are instrumented.
- `engine-heartbeat-test-support`: how the test suite drives the engine slot
  heartbeat so that heartbeat-dependent tests stay fast and deterministic.

### Modified Capabilities

- None. The change only affects test/CI infrastructure, not user-visible
  behavior.

## Impact

- `tox.ini` (PyPy environments), the coverage configuration in
  `pyproject.toml`, and `.github/workflows/tests-ubuntu.yml` (matrix entries
  and coverage flags).
- `tests/test_engine_loop.py`, plus the shared test helpers in `tests/utils/`
  that stub looping calls and prepare subprocess environments;
  `scrapy/core/engine.py` only if the heartbeat interval needs to become
  overridable for tests.
- No dependency or public API changes.
