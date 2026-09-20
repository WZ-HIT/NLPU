# Phase 0 Research: Asynchronous Callbacks in Spider Contracts

All `NEEDS CLARIFICATION` items from the plan's Technical Context were resolved by
reading the repository at base commit `c7eacdbb30a4563bbbe04ed02781768f4e19eabb`.
No open questions remain.

## Decision 1: Reuse the existing awaitable normalization instead of new plumbing

**Decision**: Normalize callback results with the existing helpers
`scrapy.utils.spider.iterate_spider_output()` and
`scrapy.utils.defer.deferred_from_coro()` rather than introducing a contract-specific
awaitable layer.

**Rationale**: `iterate_spider_output()` already implements exactly the required
mapping: an async generator is returned unchanged, a coroutine is wrapped with
`deferred_from_coro()` and re-fed through itself, and anything else is treated as an
iterable via `arg_to_iter()`. `scrapy/core/scraper.py` uses the same helper on the
crawl path, so contract checks and real crawls classify callback results identically.
This keeps the contract feature consistent with documented Scrapy behaviour and adds
no new dependency surface.

**Alternatives considered**:

- Convert coroutines to lists eagerly with `asyncio`/`ensure_future`: rejected because
  it bypasses Twisted's reactor, which the `scrapy check` command drives, and would
  break the deferred-chain integration that `ContractsManager._clean_req()` relies on.
- Add a new `async_contracts` code path guarded by a setting: rejected as unnecessary
  scope and an extra configuration knob with no user benefit.

## Decision 2: Return awaitable results from the hook wrappers unchanged in shape

**Decision**: When a callback produces an asynchronous result, the pre-hook and
post-hook wrappers return the normalized awaitable (`Deferred` for coroutines, async
iterable for async generators) instead of converting it to a list, and run
`post_process` only after the awaited objects are available.

**Rationale**: `Contract.add_post_hook()` must inspect the objects the callback
produced. For synchronous results that is the existing `list(...)` conversion. For
asynchronous results the objects do not exist yet when the wrapper returns, so the
post-processing step is deferred to the point where the awaitable resolves. Returning
the `Deferred` from the wrapper is what lets `scrapy check`'s reactor drive the check
to completion.

**Alternatives considered**:

- Blocking on the awaitable inside the wrapper: rejected because blocking the reactor
  thread is unsupported in Scrapy and would deadlock any callback that itself depends
  on the reactor (for example a callback issuing another request).

## Decision 3: Keep failure/error attribution exactly as today

**Decision**: `AssertionError` from a hook is a failure, any other exception from a hook
is an error, and an exception raised while awaiting the callback is an error for the
callback's test case. Success is recorded only after the corresponding work completes.

**Rationale**: This mirrors the existing synchronous behaviour
(`results.startTest`/`addSuccess`/`addFailure`/`addError` around the pre- and
post-process steps) and preserves the `scrapy check` output contract. It also satisfies
the edge case that a partially produced result followed by an exception must be
reported as an error, not a partial success.

**Alternatives considered**:

- Reporting asynchronous exceptions as failures: rejected because it would change the
  established meaning of failure versus error in contract output and could change
  command exit semantics for existing users.

## Decision 4: Verify at the unit level, then at the command level

**Decision**: Cover the behaviour in `tests/test_contracts.py`, which already contains
the three cases that currently assert the rejection
(`test_pre_hook_async_callback`, `test_pre_hook_async_generator`,
`test_post_hook_async_generator`) plus `test_returns_async`, and additionally exercise
the command path through `tests/test_command_check.py` where practical.

**Rationale**: `tests/test_contracts.py` drives `Contract.add_pre_hook` /
`add_post_hook` and `ContractsManager` directly, so it is the cheapest place to prove
classification and reporting. `tests/test_command_check.py` writes a temporary project
and runs the real `scrapy check` command, which is the only place that proves the
non-zero-exit-status requirement end to end.

**Alternatives considered**:

- Only adding new tests without updating the four existing rejection assertions:
  rejected because those tests encode the behaviour this feature removes, so they must
  be updated to describe the new expectation.

## Decision 5: Keep the async test suite driven by the existing Twisted helpers

**Decision**: Use the existing test utilities (`tests.utils.decorators.inline_callbacks_test`,
`scrapy.utils.test.get_crawler`, `TextTestResult`) and `pytest-twisted` support already
configured in `pyproject.toml`/`tox.ini`.

**Rationale**: The suite already has the reactor-driven fixtures these tests need
(`MockServer`, `TestProjectBase`); introducing a different async test driver would add
setup cost without improving coverage.

**Alternatives considered**:

- `pytest-asyncio`: rejected because Scrapy's test suite is built on Twisted and adding
  a second event-loop integration is out of scope.
