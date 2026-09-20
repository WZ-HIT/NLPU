## Context

See `proposal.md` — Why. Shutdown handlers are installed through
`scrapy.utils.ossignal.install_shutdown_handlers()` (SIGTERM, SIGINT and, on
Windows, SIGBREAK). Two process flavours react to them:

- `CrawlerProcess` (Twisted reactor) — `_signal_shutdown` / `_signal_kill`
  already marshal the actual stop onto the reactor with
  `reactor.callFromThread()`.
- `AsyncCrawlerProcess` (reactorless) — `_signal_shutdown_reactorless` /
  `_signal_kill_reactorless` marshal work onto the asyncio loop with
  `loop.call_soon_threadsafe()`.

In both flavours the user-facing notice was the one call that stayed inside
the handler (`self._log_shutdown(signum)` / `self._log_kill(signum)`), which is
exactly the part that is unsafe to run in a signal handler.

## Goals / Non-Goals

**Goals:**

- Make the handlers safe to run at any point of execution, including in the
  middle of a write to the handled stream.
- Keep the notices, their level, and their order relative to shutdown work
  identical to the current behaviour.
- Keep the "no loop / no reactor" early-return paths behaviourally unchanged
  apart from no longer logging from the handler.

**Non-Goals:**

- Changing where the notices are written (still the logging system), their
  wording, or their log level.
- Making the logging subsystem itself async-signal-safe.
- Changing `install_shutdown_handlers()` or any other public API.
- Reworking the graceful/forced shutdown escalation logic.

## Decisions

- **Marshal the notice onto the owning thread instead of writing it inline.**
  `CrawlerProcess` calls `reactor.callFromThread(self._log_shutdown, signum)`
  and `reactor.callFromThread(self._log_kill, signum)`; the reactorless process
  calls `loop.call_soon_threadsafe(self._log_shutdown, signum)` /
  `loop.call_soon_threadsafe(self._log_kill, signum)`. The existing order
  (notice first, then the stop/graceful-shutdown callback) is preserved because
  both calls go through the same scheduling mechanism in the same order.
  - Alternative considered: write the notice with a raw file-descriptor write
    (e.g. `os.write(2, ...)`). Rejected: it bypasses the logging system,
    changes output for users who redirect/format logs, and would not match the
    existing message expectations.
  - Alternative considered: keep logging in the handler but guard with a lock.
    Rejected: acquiring a lock in a signal handler risks deadlock or
    re-entrancy problems, and does not make `logging` signal-safe.

- **Keep `_log_shutdown` / `_log_kill` as the single place that formats the
  notices.** The only change is the caller: they are now documented as having
  to be invoked from the reactor or event loop thread rather than from the
  handler.

- **Place the reactorless scheduling after the "no loop" early return.**
  Without a loop there is no thread to log from, and the process is on its way
  down; skipping the notice here keeps the handlers from re-introducing
  handler-context logging. The escalation (installing the kill/`SIG_IGN`
  handler) still happens before the early return.

## Risks / Trade-offs

- [The notice is lost if the process dies before the loop/reactor schedules the
  callback] → The message is diagnostic only, and the previous behaviour was
  itself unreliable (it could raise `RuntimeError` and abort the shutdown). The
  escalation chain is unchanged, so a second signal still forces the shutdown.
- [The notice now comes from a different thread than before] → The logging
  system is thread-safe, and both callback queues preserve call order, so the
  user-visible message order is unchanged.
- [Existing unit tests assert that nothing is scheduled on the loop in the
  "no main task" case] → Those assertions must be updated as part of the
  change, because scheduling the notice is now intentional.
- [A process that has no reactor/loop yet no longer prints the notice] →
  Accepted: that path only exists during early startup/shutdown races where the
  escalation is the behaviour that matters.

## Migration Plan

None. The change is internal to the shutdown path and requires no user action.
Rollback is reverting the four handler bodies.

## Open Questions

None.
