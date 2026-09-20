# Feature Specification: Safe Shutdown Signal Logging

**Feature Branch**: `detect-scrapy-pr8022`

**Created**: 2026-09-19

**Status**: Draft

**Input**: PR 8022, "Do not log from the shutdown signal handlers"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Defer shutdown logging for reactor-backed processes (Priority: P1)

When a user sends a shutdown signal to a process using Twisted's reactor, Scrapy
escalates its signal handlers and emits the existing graceful/forced shutdown
messages without performing logging work in the signal handler itself.

**Why this priority**: Logging from an OS signal handler is unsafe and can
deadlock or re-enter runtime state. This is the primary defect being corrected.

**Independent Test**: Exercise `CrawlerProcessBase._signal_shutdown()` and
`_signal_kill()` with the reactor callback captured, then verify logging is
scheduled through the reactor rather than called synchronously.

**Acceptance Scenarios**:

1. **Given** a first shutdown signal, **When** the Twisted signal handler runs,
   **Then** it installs the forced-shutdown handler and schedules the graceful
   log message on the reactor.
2. **Given** a second shutdown signal, **When** the forced handler runs,
   **Then** it ignores later shutdown signals and schedules the forced-shutdown
   log message on the reactor.

---

### User Story 2 - Defer shutdown logging for reactorless processes (Priority: P2)

When a user sends a shutdown signal to a reactorless async process, Scrapy
preserves graceful and forced shutdown messages while moving logging to the
process event loop.

**Why this priority**: The reactorless path has the same signal-handler safety
problem and must remain behaviorally consistent with the reactor-backed path.

**Independent Test**: Invoke the reactorless shutdown handlers with a controlled
loop and verify that both log dispatch and task control are scheduled with
`call_soon_threadsafe()`.

**Acceptance Scenarios**:

1. **Given** a reactorless process with an active loop, **When** the first
   shutdown signal arrives, **Then** the graceful log and shutdown task are
   scheduled on that loop.
2. **Given** a reactorless process with an active loop, **When** a second
   shutdown signal arrives, **Then** the forced log is scheduled before the
   main task is cancelled.

### Edge Cases

- The reactorless loop is already absent: handler escalation must still occur,
  but no loop callback or log dispatch can be scheduled.
- The reactorless main task is absent: the forced log is still scheduled, and
  no task cancellation is attempted.
- Existing user-visible message text and shutdown semantics must remain intact.
- Repeated signals must continue to escalate in graceful-then-forced order.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Signal handlers MUST NOT call logging methods synchronously.
- **FR-002**: Twisted shutdown handlers MUST schedule existing shutdown log
  messages through `reactor.callFromThread()`.
- **FR-003**: Reactorless shutdown handlers MUST schedule existing shutdown log
  messages through `event_loop.call_soon_threadsafe()`.
- **FR-004**: Handler escalation MUST remain unchanged: first signal requests a
  graceful shutdown; a subsequent signal ignores further signals and forces
  shutdown.
- **FR-005**: The existing graceful and forced shutdown message content MUST be
  preserved.
- **FR-006**: Existing graceful-shutdown scheduling and task-cancellation
  behavior MUST remain unchanged apart from the logging dispatch mechanism.
- **FR-007**: Tests that invoke shutdown helpers MUST continue to pass without
  requiring real process-wide signal delivery.

### Key Entities

- **Shutdown Signal Event**: A signal number and frame delivered to Scrapy.
- **Deferred Log Action**: A logging call queued onto the reactor or event loop.
- **Shutdown Mode**: Graceful first-signal behavior or forced second-signal
  behavior.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All shutdown log calls in both supported process paths execute on
  their runtime's event-loop thread, with zero synchronous logging calls from
  signal-handler bodies.
- **SC-002**: Existing graceful and forced shutdown messages continue to appear
  for both process paths.
- **SC-003**: Signal escalation and shutdown behavior remain unchanged in all
  existing shutdown scenarios.
- **SC-004**: No public API or user-facing command behavior changes.

## Assumptions

- The existing message text is part of Scrapy's observable behavior and should
  be preserved.
- Logging stays in the existing `_log_shutdown()` and `_log_kill()` helpers.
- Signal-handler registration and signal selection remain unchanged.
