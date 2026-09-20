# Interface Contract: ScrapyJSONEncoder Temporal Serialization

**Feature**: 001-json-iso8601-datetimes

This contract describes the observable interface the change affects: how the project's
public JSON encoder converts Python date/time values into JSON strings. It is a library-level
contract (a Python API), not a network interface.

## Endpoint: `scrapy.utils.serialize.ScrapyJSONEncoder`

### Invocation

```text
ScrapyJSONEncoder(**json_encoder_kwargs).encode(value) -> str
```

Keyword arguments are the standard `json.JSONEncoder` options and keep working unchanged
(for example `sort_keys`, `indent`). The class remains importable from the same module path.

### Guarantees for temporal values

| Input Python value | Guaranteed output (JSON string) | Example |
|--------------------|--------------------------------|---------|
| `datetime.datetime` | ISO 8601 date and time, `T` separated, fractional seconds when present, UTC offset when present | `"2010-01-02T10:11:12"` |
| `datetime.date` (not a `datetime`) | ISO 8601 calendar date | `"2010-01-02"` |
| `datetime.time` | ISO 8601 clock time, fractional seconds when present, UTC offset when present | `"10:11:12"` |

### Guarantees for non-temporal values (unchanged)

| Input Python value | Guaranteed output |
|--------------------|------------------|
| `set` | JSON array of its members |
| `decimal.Decimal` | JSON string of the decimal |
| Deferred | JSON string |
| `Request` | JSON string `"<Request METHOD URL>"` |
| `Response` | JSON string `"<Response STATUS URL>"` |
| Any item type recognized by the item adapter | JSON object of its fields (recursively encoded) |
| Anything else | Standard `json.JSONEncoder` fallback behavior, including its error for unsupported types |

### Errors

- Unsupported types MUST still raise the standard JSON encoder error (unchanged behavior).
- No new exception types are introduced.

### Consumers bound by this contract

| Consumer | Location | Obligation |
|----------|----------|-----------|
| JSON item exporter | `scrapy/exporters.py` (`JsonItemExporter`) | Emit ISO 8601 temporal values in feed output |
| JSON Lines item exporter | `scrapy/exporters.py` (`JsonLinesItemExporter`) | Emit ISO 8601 temporal values in feed output |
| Periodic log extension | `scrapy/extensions/periodic_log.py` | Emit ISO 8601 temporal values in logged JSON |

## Compatibility note

This is an intentional textual-format change for temporal values only. Consumers that
compared the previous space-separated representation will observe a different string; that is
the point of the feature. Consumers of any non-temporal value observe no difference.
