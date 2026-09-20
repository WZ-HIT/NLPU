## Context

See proposal.md - Why. Contract hook wrappers are currently synchronous
functions. They explicitly detect coroutine and asynchronous-generator return
values and raise `TypeError`, so asynchronous callback output never reaches
`post_process`.

## Goals / Non-Goals

Goals:

- Execute coroutine and asynchronous-generator callbacks using Scrapy's existing
  coroutine/Deferred bridge.
- Keep contract hook ordering and `TestResult` accounting.
- Preserve synchronous callback behavior.

Non-goals:

- Changing contract syntax or adding asynchronous contract hook methods.
- Changing how requests, items, or callback keyword arguments are extracted.
- Supporting arbitrary awaitable objects beyond Scrapy's normal callback
  handling.

## Decisions

- Use the existing `iterate_spider_output` / `deferred_from_coro` facilities to
  normalize callback results. This keeps contract execution consistent with the
  rest of Scrapy and supports both asyncio-backed and non-asyncio reactors.
- Make the generated callback wrapper awaitable and consume asynchronous
  generators into output before invoking post-process hooks. Always collecting
  output preserves the existing `post_process(output: list)` contract.
- Update the request-cleaning wrapper as part of the same path so callback
  exceptions from asynchronous execution are added to the correct
  `TestResult`, matching the existing synchronous error behavior.
- Keep synchronous callbacks on the same wrapper path, using a normalized
  awaitable/result flow, to avoid two divergent implementations.

## Risks / Trade-offs

- [Wrapper changes can alter callback exception reporting] -> Keep the existing
  `_create_testcase(..., "callback")` error path and add focused tests for both
  coroutine and async-generator failures.
- [Async generator exhaustion can be delayed] -> Explicitly consume the entire
  stream before `post_process`, so contract checks observe all yielded output.
- [Reactor differences can change await semantics] -> Use Scrapy's existing
  `maybe_deferred_to_future`/`deferred_from_coro` helpers rather than reactor
  specific code.

## Migration Plan

No migration is required. Synchronous callbacks retain their existing behavior;
asynchronous callbacks that previously raised `TypeError` become valid contract
targets.
