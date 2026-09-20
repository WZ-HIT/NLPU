## Why

Scrapy supports coroutine and asynchronous-generator spider callbacks, but
spider contracts currently reject both with `TypeError`. This prevents contract
checks from validating modern asynchronous spiders.

## What Changes

- Allow `Contract.add_pre_hook()` and `Contract.add_post_hook()` to invoke both
  coroutine callbacks and asynchronous-generator callbacks.
- Await asynchronous callback output before contract post-processing, while
  preserving the existing behavior and ordering for synchronous callbacks.
- Route failures raised while awaiting or iterating asynchronous callback
  output through the existing contract test-result error handling.
- Preserve contract behavior when a callback returns requests, items, or a mix
  of both, including when those values are produced asynchronously.

## Capabilities

### New Capabilities

- `spider-contracts`: contract checks for synchronous and asynchronous spider
  callbacks.

### Modified Capabilities

None.

## Impact

Affected code is in `scrapy/contracts/__init__.py`; contract behavior and the
`scrapy check` command are affected. Existing synchronous contract behavior
must remain compatible. Tests are expected to change in `tests/test_contracts.py`
and may add an end-to-end async case in `tests/test_command_check.py`.
