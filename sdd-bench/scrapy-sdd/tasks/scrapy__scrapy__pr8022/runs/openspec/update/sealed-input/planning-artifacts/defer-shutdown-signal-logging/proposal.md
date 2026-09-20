## Why

Scrapy's process-level shutdown signal handlers currently emit log records
directly from within the signal handler. Logging is not async-signal-safe: if
the interrupted thread happens to be writing to the same stream that the log
handler writes to, the nested write raises `RuntimeError` and the handler dies
before it has scheduled the graceful stop. The visible result is a process
that neither shuts down gracefully nor escalates to a forced shutdown, because
the very first `Ctrl-C`/`SIGTERM` failed halfway through.

## What Changes

- Stop emitting the shutdown notices ("Received <SIGNAL>, shutting down
  gracefully…" and "Received <SIGNAL> twice, forcing unclean shutdown") from
  inside the signal handlers.
- Schedule those notices onto the thread that owns the reactor / event loop
  (Twisted `reactor.callFromThread()`, asyncio
  `loop.call_soon_threadsafe()`), so the handler itself only performs
  signal-safe work.
- Preserve the exact message text, log level, and the ordering between the
  notice and the shutdown work that follows it.
- No public API, setting, or message-format change; this is a robustness fix
  for the signal-handling path only.

## Capabilities

### New Capabilities

- `crawler-shutdown-signal-handling`: How `CrawlerProcess` /
  `AsyncCrawlerProcess` react to shutdown signals (SIGINT, SIGTERM, SIGBREAK):
  the notification they emit, and the graceful-then-forced shutdown
  escalation that the handlers drive.

### Modified Capabilities

None. This project has no existing specs for the process shutdown path.

## Impact

- `scrapy/crawler.py`: `CrawlerProcess._signal_shutdown`,
  `CrawlerProcess._signal_kill`,
  `AsyncCrawlerProcess._signal_shutdown_reactorless`,
  `AsyncCrawlerProcess._signal_kill_reactorless` (the `_log_shutdown` /
  `_log_kill` helpers stay as they are, but are now invoked from the
  reactor/loop thread).
- Tests covering the shutdown helpers and the end-to-end shutdown notices:
  `tests/test_crawler.py` (the assertion that nothing is scheduled on the loop
  when there is no main task no longer holds) and
  `tests/test_crawler_subprocess.py` (graceful / forced shutdown notices).
- No dependency or configuration changes.
