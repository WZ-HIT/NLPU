# Data Model: Safe Shutdown Signal Logging

## Shutdown Signal Event

- **Fields**: signal number, optional frame, active process type
- **Validation**: signal number must exist in Scrapy's signal-name mapping before
  logging.
- **Relationship**: Starts one transition in process shutdown state.

## Shutdown Mode

- **States**: `graceful`, `forced`
- **Transitions**:
  - `running -> graceful` on the first shutdown signal.
  - `graceful -> forced` on the next shutdown signal.
  - `forced -> forced` for subsequent signals, which are ignored.

## Deferred Log Action

- **Fields**: logger callable, signal number, target execution context
- **Validation**: must be queued on the reactor or active event loop.
- **Relationship**: Emits the graceful message before graceful shutdown work or
  the forced message before forced task cancellation.
