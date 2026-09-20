# Requirements Document

## Introduction

Scrapy installs OS signal handlers (SIGINT, SIGTERM, and SIGBREAK on Windows) so that a crawl can be stopped gracefully, and forcibly on a second signal. The handlers in `scrapy/crawler.py` currently write log records directly from the handler body (`_log_shutdown`, `_log_kill`). A signal can interrupt the process at any point, including in the middle of an I/O write to the same stream that the logging framework targets. Logging from the handler is therefore not safe: the write can raise `RuntimeError`, and the exception escapes the handler before the escalation step, leaving the shutdown unfinished. This feature makes the shutdown log messages safe to emit while preserving the operator-visible behaviour of the shutdown messages.

## Boundary Context

- **In scope**: the shutdown/kill signal handlers of `CrawlerProcess` and `AsyncCrawlerProcess` (`_signal_shutdown`, `_signal_kill`, `_signal_shutdown_reactorless`, `_signal_kill_reactorless`) and the `_log_shutdown` / `_log_kill` helpers they call.
- **Out of scope**: installation of the handlers themselves (`scrapy.utils.ossignal.install_shutdown_handlers`), which signals are intercepted, the graceful/forced shutdown policy, and the exit codes of the process.
- **Adjacent expectations**: log message text, log level, and destination remain as they are today; the logging framework is still configured by Scrapy and is not replaced or bypassed.

## Requirements

### Requirement 1: No logging from a signal handler

**Objective:** As a Scrapy operator, I want the shutdown signal handlers to never perform logging work themselves, so that a signal delivered mid-write can never break the shutdown sequence.

#### Acceptance Criteria

1. When a shutdown or kill signal handler runs, the system shall not call the logging framework synchronously from within the handler.
2. When a shutdown or kill signal handler runs, the system shall complete its escalation logic (installing the next handler and scheduling shutdown) independently of whether the log message can be emitted.
3. If emitting a shutdown log message fails, then the system shall still proceed with the graceful or forced shutdown.
4. The system shall keep the `_log_shutdown` and `_log_kill` helpers as the single source of the shutdown messages, so the deferred emission cannot silently change the message text.

### Requirement 2: Logging is deferred to the event loop thread

**Objective:** As a Scrapy operator, I want the shutdown messages to be emitted from the reactor or event loop thread, so that the messages are written on the same thread that owns the logging stream.

#### Acceptance Criteria

1. When the Twisted reactor is used and a shutdown signal is received, the system shall schedule the shutdown message on the reactor via `reactor.callFromThread`.
2. When the Twisted reactor is used and a second (kill) signal is received, the system shall schedule the kill message on the reactor via `reactor.callFromThread`.
3. When no Twisted reactor is used and a shutdown signal is received, the system shall schedule the shutdown message on the asyncio loop via `loop.call_soon_threadsafe`.
4. When no Twisted reactor is used and a kill signal is received, the system shall schedule the kill message on the asyncio loop via `loop.call_soon_threadsafe`.
5. Where no event loop is available to the handler, the system shall skip the deferred message and continue with the remaining handler logic without error.

### Requirement 3: Operator-visible shutdown messages are preserved

**Objective:** As a Scrapy operator, I want the existing shutdown messages to still appear, so that scripts and human operators can keep relying on them.

#### Acceptance Criteria

1. When the first shutdown signal is received, the system shall still emit "Received <SIGNAL>, shutting down gracefully. Send again to force".
2. When a second shutdown signal is received, the system shall still emit "Received <SIGNAL> twice, forcing unclean shutdown".
3. While a shutdown is in progress, the system shall emit the deferred shutdown message before or independently of the shutdown action it was queued with.
4. The system shall not introduce new log records, new log levels, or new output streams for shutdown.
