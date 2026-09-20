---
description: "Task list for supporting asynchronous callbacks in spider contracts"
---

# Tasks: Asynchronous Callbacks in Spider Contracts

**Input**: Design documents from `/specs/001-async-contract-callbacks/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/contract-hooks.md

**Tests**: Test tasks are included because the feature changes behaviour that is
currently asserted by existing tests (the four rejection assertions in
`tests/test_contracts.py` must change with the feature).

## Phase 1: Setup

- [ ] T001 Confirm the current rejection sites in `scrapy/contracts/__init__.py` (`Contract.add_pre_hook`, `Contract.add_post_hook`, `ContractsManager._clean_req`) and the four tests in `tests/test_contracts.py` that assert them (`test_returns_async`, `test_pre_hook_async_callback`, `test_pre_hook_async_generator`, `test_post_hook_async_generator`).
- [ ] T002 [P] Confirm the reusable awaitable helpers in `scrapy/utils/spider.py` (`iterate_spider_output`) and `scrapy/utils/defer.py` (`deferred_from_coro`, `ensure_awaitable`) cover the result shapes listed in `data-model.md`.

---

## Phase 2: Foundational

- [ ] T003 Add a shared helper in `scrapy/contracts/__init__.py` that classifies a callback result as synchronous iterable, coroutine, async generator, or other awaitable, returning the normalized objects or an awaitable that resolves to them (reusing `iterate_spider_output`).
- [ ] T004 Update the type annotations in `scrapy/contracts/__init__.py` so hook wrappers may return either `list[Any]` or a `Deferred`, keeping mypy clean.

---

## Phase 3: User Story 1 - Contract checks accept asynchronous callbacks (P1)

**Goal**: Coroutine callbacks run and are counted by `@returns` / `@scrapes` instead of raising "Contracts don't support async callbacks".

**Independent Test**: A coroutine callback that returns the expected objects passes; one that returns the wrong number fails; one that raises produces an error.

### Tests for User Story 1

- [ ] T005 [P] [US1] Update `TestContractsManager.test_returns_async` in `tests/test_contracts.py` to expect the coroutine callback result to be evaluated by `@returns` instead of asserting `should_error()`.
- [ ] T006 [P] [US1] Add a failing-expectation case for a coroutine callback (wrong `@returns` range) in `tests/test_contracts.py`, asserting a contract failure rather than an error.
- [ ] T007 [P] [US1] Add a raising-coroutine case in `tests/test_contracts.py`, asserting the exception is recorded as a contract error for the callback test case.

### Implementation for User Story 1

- [ ] T008 [US1] Replace the `TypeError("Contracts don't support async callbacks")` branch for coroutine results in `Contract.add_pre_hook` with normalization that records `pre_process` before invoking the callback and returns the awaitable. Depends on T003.
- [ ] T009 [US1] Apply the equivalent change to coroutine results in `Contract.add_post_hook`, running `post_process` in the deferred continuation. Depends on T003.
- [ ] T010 [US1] Update `ContractsManager._clean_req` in `scrapy/contracts/__init__.py` so coroutine callback results are awaited and their exceptions are recorded as contract errors. Depends on T003.

**Checkpoint**: Coroutine callbacks are fully supported and independently verifiable.

---

## Phase 4: User Story 2 - Async generator callbacks (P2)

**Goal**: Async generator callbacks are consumed and counted by contracts.

**Independent Test**: An async generator yielding the expected objects passes; one yielding too few fails.

### Tests for User Story 2

- [ ] T011 [P] [US2] Update `TestCustomContractPrePostProcess.test_pre_hook_async_generator` in `tests/test_contracts.py` to expect success instead of the rejection error.
- [ ] T012 [P] [US2] Update `TestCustomContractPrePostProcess.test_post_hook_async_generator` in `tests/test_contracts.py` so `post_process` receives the yielded objects.
- [ ] T013 [P] [US2] Add a failing-expectation async-generator case in `tests/test_contracts.py`, asserting the failure names the expected range.

### Implementation for User Story 2

- [ ] T014 [US2] Handle async-generator results in `Contract.add_pre_hook` / `Contract.add_post_hook` in `scrapy/contracts/__init__.py` as async iterables rather than rejecting them. Depends on T003.
- [ ] T015 [US2] Ensure `ContractsManager._clean_req` records the async-generator callback outcome once the async iterable is exhausted, and that a partially consumed generator leaves no unretrieved failure. Depends on T010.

**Checkpoint**: Both asynchronous callback shapes work.

---

## Phase 5: User Story 3 - Hooks and command exit status (P3)

**Goal**: Custom contract hooks report correctly for asynchronous callbacks, and `scrapy check` returns the right exit status.

**Independent Test**: A hook assertion failure yields a failure, a raising hook yields an error, and a failing async contract makes `scrapy check` exit non-zero.

### Tests for User Story 3

- [ ] T016 [P] [US3] Update `TestCustomContractPrePostProcess.test_pre_hook_async_callback` in `tests/test_contracts.py` to assert the `pre_process` outcome is recorded for a coroutine callback.
- [ ] T017 [P] [US3] Add assertion-failure and error cases for hooks attached to asynchronous callbacks in `tests/test_contracts.py`.
- [ ] T018 [P] [US3] Add an async-callback contract case to `tests/test_command_check.py` covering the `scrapy check` command exit status.

### Implementation for User Story 3

- [ ] T019 [US3] Verify and, if needed, adjust hook outcome recording for asynchronous results in `scrapy/contracts/__init__.py` so `AssertionError` is a failure, other exceptions are errors, and success is recorded only after completion.
- [ ] T020 [US3] Confirm no change is needed in `scrapy/commands/check.py` for exit-status handling; adjust only if the deferred result is not awaited before the run finishes.

**Checkpoint**: All three user stories are independently verifiable.

---

## Phase 6: Polish

- [ ] T021 [P] Add an asynchronous callback example to `docs/topics/contracts.rst`.
- [ ] T022 [P] Validate the documented scenarios in `quickstart.md` against the implemented behaviour.
- [ ] T023 Confirm `tests/test_utils_spider.py` still covers the `iterate_spider_output()` contract used by this feature, and extend it only if a new result shape was introduced.

---

## Dependencies & Execution Order

- Phase 1 -> Phase 2 -> Phases 3/4/5 (each user story can proceed once T003/T004 are done).
- T008/T009/T010 depend on T003; T014/T015 depend on T003 and T010.
- Tests for a story should be updated before or alongside the implementation that flips them, because the pre-existing assertions encode the removed rejection.

## Parallel Opportunities

- T005/T006/T007, T011/T012/T013, and T016/T017/T018 touch test files and can be drafted in parallel, but T005-T018 all edit `tests/test_contracts.py`, so serialise edits within that file.
- T021 and T023 are independent of each other and of the core implementation.

## Implementation Strategy

MVP is Phase 3 (User Story 1): coroutine callbacks evaluated by contracts. Phase 4
adds the async-generator shape, and Phase 5 closes the loop on hook attribution and
command exit status.
