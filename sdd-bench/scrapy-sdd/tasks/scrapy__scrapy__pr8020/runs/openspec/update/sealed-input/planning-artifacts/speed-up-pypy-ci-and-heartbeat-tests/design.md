## Context

- `pyproject.toml` sets `[tool.coverage.run] patch = ["subprocess"]`, so every
  test environment that runs pytest with `--cov-config=pyproject.toml`
  (`[testenv]`, `[min]`, `[testenv:pypy3]`, ...) also starts coverage inside
  subprocesses spawned by the tests. `[testenv:min-pypy3]` already runs with
  `; disabling coverage` and no `--cov`.
- The engine starts a slot heartbeat when it begins processing start requests
  (`scrapy/core/engine.py`: `create_looping_call(...)`,
  `heartbeat.start(self._SLOT_HEARTBEAT_INTERVAL)` with a 5 second interval).
  `tests/test_engine_loop.py::TestMain::test_sleep` and
  `tests/test_engine_loop.py::TestRequestSendOrder::test_lazy` depend on those
  repeated calls, so they are bounded by the production interval.
- `tests/utils/__init__.py` already provides `OneShotLoop`/`TwoShotLoop`
  stubs, and `tests/test_extension_memusage.py` already monkeypatches
  `scrapy.core.engine.create_looping_call` with them.

## Goals / Non-Goals

**Goals:**

- Remove subprocess coverage instrumentation from the PyPy test environment so
  the PyPy CI job is no longer dominated by it.
- Make the heartbeat-dependent tests independent of the 5 second production
  interval without weakening what they assert.
- Keep coverage reporting for the CPython jobs unchanged.

**Non-Goals:**

- Changing the production heartbeat interval or how the engine processes
  scheduled requests.
- Adding public settings or APIs for the heartbeat.
- Removing coverage from CPython environments or changing Codecov settings.

## Decisions

1. **Disable subprocess coverage only for PyPy, keep in-process coverage.**
   The PyPy tox environment gets a coverage configuration without
   `patch = ["subprocess"]` (a dedicated config file, or the equivalent
   option-level override passed through the environment) instead of dropping
   coverage entirely, matching the intent of the pull request: no
   PyPy-specific coverage information is lost, but the slow part is gone.
   *Alternatives considered:* keeping the status quo (PyPy stays slow) and
   mirroring `[testenv:min-pypy3]`, which disables coverage completely for the
   minimum-dependency PyPy job. Going fully uncovered is acceptable too, but
   keeping in-process coverage is a smaller behavior change and keeps the
   PyPy job comparable with the current output.
2. **Drive the heartbeat from the tests instead of shortening it in
   production.** Tests override the heartbeat for their own crawler (short
   interval or a stub looping call injected where the engine builds it), so the
   5 second interval remains the production behavior and no new public
   configuration is introduced. *Alternatives considered:* turning the
   interval into a setting (public API surface with no user-facing need) and
   reducing the constant globally (slower-churn production behavior).
3. **Reuse the existing test stubs.** `tests/utils/__init__.py` already hosts
   looping-call stubs that other tests monkeypatch into
   `scrapy.core.engine.create_looping_call`; extend/reuse that helper rather
   than introducing a second stubbing mechanism, and keep the engine's public
   surface untouched.

## Risks / Trade-offs

- Coverage gaps on PyPy-specific code paths → the CPython coverage jobs already
  cover the same files, and `[testenv:min-pypy3]` demonstrates that the project
  accepts an uncovered PyPy job; document the decision in the news entry.
- Tests using a very short heartbeat could become timing-sensitive → keep the
  existing explicit waits/assertions in the tests and tune the test interval
  only as far as needed to remove the multi-second waits.
- A test-only stub could drift from the real looping-call contract → assert the
  heartbeat lifecycle (start while the slot is open, stop on slot close) where
  the stub is used.

## Open Questions

- Whether the PyPy coverage configuration lives in a dedicated file or is
  passed as an environment override is an implementation detail that does not
  change the specs or the task breakdown.
