# Phase 1 Data Model: Asynchronous Callbacks in Spider Contracts

This feature has no persistent storage. The entities below are the in-memory
concepts a contract check manipulates; they describe the shapes the implementation
must preserve or newly support.

## Entity: Spider Callback

The callable a spider method carries, attached to the sample request produced by a
contract.

| Attribute | Type | Notes |
|-----------|------|-------|
| `method` | callable | The bound spider method the contracts were extracted from. |
| `__name__` | string | Used in test-case identifiers, e.g. `returns_request`. |
| `result shape` | enum | One of `sync-iterable`, `coroutine`, `async-generator`, `awaitable`. |

**Validation rules**

- The callback must be callable with `(response, **cb_kwargs)`; the existing contract
  extraction already enforces the accepted argument counts.
- A coroutine result must be awaited exactly once; a coroutine result must never be
  closed and discarded (the current rejection path calls `cb_result.close()`).
- An async generator result must be consumed as an async iterable, and must not be
  passed to `arg_to_iter()`.

**State transitions for a callback result**

```text
callback called
  ├── sync iterable / item / request -> list(...) as today
  ├── coroutine -> Deferred (deferred_from_coro) -> awaited -> objects -> list(...)
  ├── async generator -> async iterable -> consumed -> list(...)
  └── other awaitable -> awaited -> objects -> list(...)
```

## Entity: Contract

An annotation extracted from a callback docstring.

| Attribute | Type | Notes |
|-----------|------|-------|
| `name` | string | Contract name used in the docstring (`url`, `returns`, `scrapes`, custom). |
| `method` | callable | The callback the contract belongs to. |
| `args` | tuple | Whitespace-separated docstring arguments. |
| `testcase_pre` | `TestCase` | Synthetic test case for the pre-hook outcome. |
| `testcase_post` | `TestCase` | Synthetic test case for the post-hook outcome. |

**Validation rules**

- `pre_process` and `post_process` are optional; when absent, the corresponding test
  case is never started or recorded (unchanged from today).
- `adjust_request_args()` continues to run at extraction time, before any callback is
  invoked, and therefore needs no asynchronous handling.

## Entity: Contract Hook Outcome

The recorded result of one hook or callback execution.

| Attribute | Type | Notes |
|-----------|------|-------|
| `testcase` | `TestCase` | Identifies callback, hook, and spider, e.g. `[demo_spider] returns_request (@returns pre-hook)`. |
| `outcome` | enum | `success`, `failure`, `error`. |
| `exc_info` | tuple or null | Present for `failure` and `error`. |

**Validation rules**

- `AssertionError` maps to `failure`; any other exception maps to `error`.
- Success is recorded only after the asynchronous work for that step has completed.
- One callback result can produce at most one outcome per hook plus the callback
  outcome itself.

## Entity: Contract Check Run

The aggregate produced by `scrapy check` for one spider.

| Attribute | Type | Notes |
|-----------|------|-------|
| `results` | `TextTestResult` | Collects successes, failures, and errors. |
| `exit_status` | integer | Zero only when there are no failures and no errors. |
| `elapsed` | duration | Already printed in the command summary. |

**Validation rules**

- The command must remain bounded: an asynchronous callback must not leave an
  un-awaited coroutine or an unretrieved `Deferred` failure behind when the reactor
  stops.
- The set of sample requests generated for a spider must not change, so the number of
  contracts run is unchanged by this feature.
