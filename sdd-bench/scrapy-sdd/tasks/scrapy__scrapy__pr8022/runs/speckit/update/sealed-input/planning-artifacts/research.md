# Research: Safe Shutdown Signal Logging

## Decision: Queue Twisted logging with `callFromThread`

**Rationale**: `CrawlerProcessBase._signal_shutdown()` and `_signal_kill()` run
in the signal-handler path. Scheduling `_log_shutdown()` and `_log_kill()` with
`reactor.callFromThread()` moves logging to reactor execution without changing
the messages or shutdown actions.

**Alternatives considered**:

- Keep synchronous logging: rejected because that is the defect.
- Remove shutdown messages: rejected because it changes user-visible behavior.

## Decision: Queue reactorless logging with `call_soon_threadsafe`

**Rationale**: The reactorless handlers already use the event loop for task
control. Scheduling the existing logging helpers on the same loop keeps logging
off the signal-handler path and preserves ordering relative to shutdown work.

**Alternatives considered**:

- Log only when a loop exists: rejected because the required behavior should
  remain consistent with the reactor-backed path when a loop is active.
- Fold logging into task callbacks: rejected because it complicates ordering and
  is unnecessary.

## Decision: Preserve handler escalation and message text

**Rationale**: The change is a thread-safety correction, not a UX or lifecycle
redesign. Existing tests and subprocess assertions establish the expected
graceful and forced shutdown messages.

**Alternatives considered**:

- Change wording or severity: rejected as unrelated scope.
