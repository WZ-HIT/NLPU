## Purpose

Defines how Scrapy's process entry points behave when the user or the
environment asks a running crawl to stop by sending a shutdown signal, so that
stopping is always possible even when the process is in the middle of writing
to a stream.

## ADDED Requirements

### Requirement: Shutdown signal handlers perform signal-safe work only

When a shutdown signal is received, the installed handler SHALL NOT emit log
records, write to standard output/error, or otherwise run code that is not
async-signal-safe. The handler SHALL limit itself to installing the follow-up
handler and scheduling the remaining work on the thread that owns the reactor
or event loop.

#### Scenario: First shutdown signal while a stream write is in progress

- **WHEN** a shutdown signal arrives while the main thread is writing to the
  same stream that the logging system writes to
- **THEN** the handler completes without raising an error
- **AND** the graceful shutdown is still scheduled

#### Scenario: Forced shutdown signal while a stream write is in progress

- **WHEN** a second shutdown signal arrives after the graceful shutdown has
  been requested, while the logging stream is busy
- **THEN** the handler completes without raising an error
- **AND** the forced shutdown is still scheduled

### Requirement: Shutdown notices still reach the user

The shutdown notices SHALL still be emitted once per signal, with the same
text as before: a first signal reports that the process is shutting down
gracefully and that sending the signal again forces a shutdown, and a second
signal reports that the shutdown is being forced.

#### Scenario: Graceful shutdown notice

- **WHEN** the first shutdown signal is received by a running process
- **THEN** a notice containing "shutting down gracefully" is written
- **AND** a notice containing "forcing unclean shutdown" is not written yet

#### Scenario: Forced shutdown notice

- **WHEN** a second shutdown signal is received before the graceful shutdown
  finished
- **THEN** a notice containing "forcing unclean shutdown" is written

### Requirement: Notices are ordered before the shutdown work they announce

The notice for a given signal SHALL be emitted before the shutdown work
scheduled by that same signal runs, so that the user-visible order of messages
relative to spider/engine shutdown is unchanged.

#### Scenario: Message order is preserved

- **WHEN** the process receives a shutdown signal
- **THEN** the graceful notice appears before the crawl reports that the
  spider was closed because of the shutdown

### Requirement: Signal handling degrades safely without a reactor or loop

When no reactor or event loop is available, the handlers SHALL still install
the next handler in the escalation chain (forced shutdown after the first
signal, and ignoring further signals after the second) instead of failing or
blocking on a missing loop.

#### Scenario: First signal without an event loop

- **WHEN** the first shutdown signal is received and there is no event loop to
  schedule work on
- **THEN** the forced-shutdown handler is installed

#### Scenario: Second signal without an event loop

- **WHEN** the second shutdown signal is received and there is no event loop to
  schedule work on
- **THEN** further shutdown signals are ignored
