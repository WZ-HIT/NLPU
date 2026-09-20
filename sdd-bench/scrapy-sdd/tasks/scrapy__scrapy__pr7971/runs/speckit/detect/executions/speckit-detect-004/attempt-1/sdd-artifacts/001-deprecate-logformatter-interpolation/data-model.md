# Phase 1 Data Model: Log Formatter Adapter

## Log Formatter Result

The dictionary returned by a `LogFormatter` method.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `level` | integer | No | Defaults to `logging.INFO` when absent, matching current behavior |
| `msg` | string or `None` | No | Absent or falsy values become `""` |
| `args` | mapping, tuple, `None` | No | Explicit interpolation arguments; absence triggers the deprecated dict path |

**Validation rules**

- A result must only be adapted when it is not `None`; suppression is handled by
  the caller before the adapter runs.
- `args` that are present and truthy keep their current handling: tuple values
  become positional logging arguments, mapping values become a single mapping
  argument.
- Empty tuple or empty mapping `args` continue to be treated as no arguments.

## Departure / Warning State

Legacy dict-interpolation reliance is identified by a truthy, non-empty `msg`
combined with a missing or empty `args`, where the returned result dictionary is
used as the interpolation mapping.

| State | Trigger | Observable result |
|-------|---------|-------------------|
| Explicit args | `args` is a non-empty tuple or mapping | Log text from explicit args; no warning |
| No placeholders, no args | `args` empty and `msg` has no mapping placeholders | Message unchanged; no warning |
| Legacy dict interpolation | `args` empty and `msg` has mapping placeholders | Message interpolated from result dictionary; deprecation warning |

## Relationships

- The adapter consumes one log formatter result and produces the positional
  arguments for a stdlib `logging` call.
- Callers in the scraper and engine pass results through unchanged, so they need
  no data-model change.
