# Phase 1 Data Model: ISO 8601 Date and Time Serialization in ScrapyJSONEncoder

**Feature**: 001-json-iso8601-datetimes

This feature has no persisted entities. The "model" is the mapping between temporal input
values and their serialized JSON representation, plus the boundary of values that must not
change.

## Entity: ScrapyJSONEncoder

The JSON encoder subclass responsible for converting values that the JSON standard library
cannot represent natively.

| Field / member | Kind | Notes |
|----------------|------|-------|
| `default(value)` | behavior | Dispatches on the runtime type of `value` |
| temporal branches | behavior | Handles `datetime`, then `date`, then `time` (order matters) |
| `DATE_FORMAT`, `TIME_FORMAT` | class attributes | Legacy format holders; no longer govern temporal output |
| constructor keyword arguments | configuration | Forwarded from the exporters; behavior unchanged |

**Validation rules**

- The date/time branches must be evaluated before any generic object handling so temporal
  values never reach the fallback path.
- The `datetime` branch must be evaluated before the `date` branch, because `datetime` is a
  subclass of `date`.

**Relationships**

- Consumed by `JsonItemExporter` and `JsonLinesItemExporter` (JSON feeds).
- Consumed by the periodic log extension (timing and stats output).

## Entity: Temporal value

Any `datetime`, `date`, or `time` instance appearing in an item, a stats entry, or a log
payload.

| Attribute | Applies to | Serialization effect |
|-----------|-----------|----------------------|
| year, month, day | `date`, `datetime` | Emitted as `YYYY-MM-DD` |
| hour, minute, second | `time`, `datetime` | Emitted as `HH:MM:SS` |
| microsecond | `time`, `datetime` | Emitted as an optional `.ffffff` fraction when non-zero |
| tzinfo / utcoffset | `time`, `datetime` | Emitted as an optional `±HH:MM` suffix when present |
| fold | `datetime`, `time` | Not representable in ISO 8601 text; ignored on serialization |

**State transitions**: none. The mapping is a pure function from a temporal value to a string.

## Serialization mapping (authoritative)

| Input type | Serialized JSON value | Example |
|------------|----------------------|---------|
| `datetime` (naive, no microseconds) | ISO 8601 date-time, `T` separator | `2010-01-02T10:11:12` |
| `datetime` (with microseconds) | ISO 8601 date-time with fraction | `2015-01-01T01:01:01.000001` |
| `datetime` (aware) | ISO 8601 date-time with offset | `2010-01-02T10:11:12+00:00` |
| `date` | ISO 8601 calendar date | `2010-01-02` |
| `time` (naive) | ISO 8601 clock time | `10:11:12` |
| `time` (aware) | ISO 8601 clock time with offset | `10:11:12+00:00` |

## Unchanged mapping (non-regression boundary)

| Input type | Serialized JSON value |
|------------|-----------------------|
| `set` | JSON array of its members |
| `decimal.Decimal` | String form of the decimal |
| Deferred | String form of the value |
| Request | `"<Request METHOD URL>"` |
| Response | `"<Response STATUS URL>"` |
| Item (any supported item type) | JSON object of its fields, recursively encoded |
