## 1. PyPy coverage configuration

- [ ] 1.1 Give the PyPy test environment a coverage configuration that does not
      patch subprocesses, wired through `tox.ini`; verify inside the environment
      that the effective coverage configuration reports no subprocess patching
      (for example `python -m coverage debug config` shows no `run.patch`
      entry).
- [ ] 1.2 Keep the CPython environments on the current configuration; verify
      that `[testenv]`/`[min]` still pass `--cov-config=pyproject.toml` with the
      subprocess patch enabled.
- [ ] 1.3 Align the CI matrix in `.github/workflows/tests-ubuntu.yml` with the
      new PyPy behavior (coverage flags for the PyPy entries) and verify the
      workflow file is still valid YAML and consistent with the tox
      environments it invokes.
- [ ] 1.4 Run a subprocess-heavy test in the PyPy environment and confirm the
      test no longer leaves coverage data from child processes behind and runs
      noticeably faster than before.

## 2. Fast heartbeat for heartbeat-dependent tests

- [ ] 2.1 Provide the test-only way to drive the engine slot heartbeat quickly
      (reusing/extending the looping-call stubs in `tests/utils/__init__.py`,
      or overriding the interval for the test crawler) and verify the helper is
      used by no production code path.
- [ ] 2.2 Update `tests/test_engine_loop.py::TestMain::test_sleep` to use the
      fast heartbeat and verify the test still asserts the documented request
      order and finishes in well under the previous runtime
      (`pytest tests/test_engine_loop.py -k test_sleep --durations=1`).
- [ ] 2.3 Audit `tests/test_engine_loop.py` for the other heartbeat-dependent
      tests (for example `TestRequestSendOrder::test_lazy`, which waits for
      `signals.scheduler_empty`) and apply the same mechanism where they wait on
      the production interval.
- [ ] 2.4 Verify the heartbeat lifecycle is still exercised: the heartbeat
      starts when start-request processing begins and stops when the spider
      slot closes (`pytest tests/test_engine_close_spider.py`).

## 3. Documentation and validation

- [ ] 3.1 Add the news entry describing the PyPy CI speed-up and the faster
      heartbeat-dependent tests, following the project's `docs/news.rst`
      format.
- [ ] 3.2 Run the affected test modules on CPython to confirm nothing regressed
      (`pytest tests/test_engine_loop.py tests/test_extension_memusage.py
      tests/test_engine_close_spider.py`).
