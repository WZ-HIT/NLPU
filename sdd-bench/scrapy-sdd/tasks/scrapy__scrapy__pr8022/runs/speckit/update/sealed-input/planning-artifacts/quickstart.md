# Quickstart Validation: Safe Shutdown Signal Logging

This planning task does not run tests or modify project code.

## Expected Implementation Checks

1. Inspect `scrapy/crawler.py` and confirm no logging call remains directly in
   `_signal_shutdown()`, `_signal_kill()`,
   `_signal_shutdown_reactorless()`, or `_signal_kill_reactorless()`.
2. Confirm Twisted paths queue logging with `reactor.callFromThread()`.
3. Confirm reactorless paths queue logging with `loop.call_soon_threadsafe()`.
4. Confirm graceful/forced handler escalation and task control are otherwise
   unchanged.

## Validation Scenarios

- First signal: graceful message is scheduled, then graceful shutdown begins.
- Second signal: forced message is scheduled, then forced shutdown begins.
- Reactorless loop absent: handler escalation still occurs without scheduling a
  loop callback.
- Reactorless main task absent: forced message is still scheduled and no task is
  cancelled.

The implementation phase may run the repository's focused crawler tests; this
detect phase must not.
