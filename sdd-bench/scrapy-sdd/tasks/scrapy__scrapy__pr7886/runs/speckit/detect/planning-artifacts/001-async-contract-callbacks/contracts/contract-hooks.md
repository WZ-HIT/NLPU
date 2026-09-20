# Interface Contract: Contract Hooks and Callback Result Handling

Internal interface between `scrapy.contracts` and the `scrapy check` command. Only
result handling changes; argument shapes and naming stay as they are today.

## `Contract.add_pre_hook(request, results) -> Request`

- Returns a request whose `callback` is a wrapper. The wrapper runs `pre_process`
  (when defined), records its outcome, then calls the original callback.
- The wrapper must **not** raise `TypeError("Contracts don't support async callbacks")`
  for asynchronous callbacks.
- Wrapper return value by original callback result:

| Original result | Wrapper returns | `pre_process` recorded |
|-----------------|-----------------|------------------------|
| sync item/request/iterable | `list[Any]` (as today) | before the callback call |
| coroutine | `Deferred` resolving to `list[Any]` | before the callback call |
| async generator | async iterable yielding the produced objects | before the callback call |

## `Contract.add_post_hook(request, results) -> Request`

- Runs `post_process` (when defined) with the objects the callback produced, then
  records the outcome.
- For asynchronous results the objects are only available once the awaitable
  resolves, so `post_process` must run in the deferred continuation, and the wrapper
  must return the awaitable so the reactor can drive it.

| Original result | `post_process` receives | Wrapper returns |
|-----------------|-------------------------|-----------------|
| sync item/request/iterable | `list[Any]` (as today) | `list[Any]` |
| coroutine | `list[Any]` after resolution | `Deferred` resolving to `list[Any]` |
| async generator | `list[Any]` after consumption | async iterable |

## `ContractsManager._clean_req(request, method, results)`

- Wraps `request.callback` so the callback outcome is recorded as a synthetic test
  case and exceptions are turned into contract errors instead of propagating.
- Must await/normalize asynchronous callback results through
  `iterate_spider_output()` so a coroutine becomes a `Deferred` rather than raising
  "coroutine is not iterable".
- Must keep `errback` wrapping unchanged.

## Outcome mapping (applies to hooks and callback)

| Raised | Recorded as | `scrapy check` exit status |
|--------|-------------|----------------------------|
| nothing | success | unchanged (0 if all contracts pass) |
| `AssertionError` | failure | non-zero |
| other `Exception` | error | non-zero |

## Compatibility guarantee

Callers relying on synchronous behaviour see identical request objects, identical
test-case identifiers, and identical success/failure/error attribution.
