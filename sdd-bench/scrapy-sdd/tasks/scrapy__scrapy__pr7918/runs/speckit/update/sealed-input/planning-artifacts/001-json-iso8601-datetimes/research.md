# Phase 0 Research: ISO 8601 Date and Time Serialization in ScrapyJSONEncoder

**Feature**: 001-json-iso8601-datetimes

No `[NEEDS CLARIFICATION]` markers remained after specification, so research focused on
choosing between the reasonable implementation options and confirming the blast radius.

## Decision: Emit the standard-library ISO 8601 representation of each temporal value

- **Decision**: Serialize `datetime`, `date`, and `time` values using the standard-library ISO
  8601 representation of the object (`isoformat()`), rather than a hand-built format string.
- **Rationale**: The request explicitly asks for ISO 8601. The standard-library
  representation is the canonical definition of ISO 8601 for these types in Python: it emits
  `YYYY-MM-DDTHH:MM:SS[.ffffff][±HH:MM]` for `datetime`, `YYYY-MM-DD` for `date`, and
  `HH:MM:SS[.ffffff][±HH:MM]` for `time`. It also preserves microseconds and UTC offsets,
  which a fixed format string does not, and it keeps the change free of new dependencies.
- **Alternatives considered**:
  - *Keep `strftime` with a new `DATE_FORMAT`/`TIME_FORMAT`*: rejected because the class
    attributes cannot express optional fractional seconds or UTC offsets, so round-tripping
    would still be lossy; it would also leave the encoder's public class attributes as the
    documented way to change the format, which is not what the request asks for.
  - *Use a third-party ISO 8601 library*: rejected as an unnecessary runtime dependency for
    behavior the standard library already provides.
  - *Emit the values as epoch numbers*: rejected because the request is explicitly about ISO
    8601 strings and because it would be a larger, breaking change to consumers.

## Decision: Apply the change only inside the JSON encoder

- **Decision**: Change only the JSON encoder's temporal branches; leave every other
  serializer (CSV, XML, pickle, marshal, pprint, python) untouched.
- **Rationale**: The request is scoped to the JSON encoder and to the issue it resolves. The
  other exporters convert values with `str()`/`repr()`-style paths and were not reported as
  problematic; widening the change would increase the regression surface for no requested
  benefit.
- **Alternatives considered**:
  - *Introduce a shared temporal-to-string helper used by all exporters*: rejected as scope
    creep for this change; it can be revisited independently if a similar issue is filed for
    the other formats.

## Decision: Rely on type-check ordering instead of explicit subclass handling

- **Decision**: Keep the existing branch order in the encoder (more specific temporal types
  checked before the more general ones) so that a `datetime` is never handled by the `date`
  branch.
- **Rationale**: `datetime` is a subclass of `date`, so ordering is what preserves the time
  component. This is an existing property of the encoder that the change must not disturb.
- **Alternatives considered**:
  - *Re-order or merge the branches with `type() is` checks*: rejected as an unnecessary
    behavioral change; subclasses of `datetime` (for example pandas' timestamp-like types)
    should keep taking the `datetime` branch.

## Consumer inventory (blast radius)

The encoder is referenced from exactly three places in the repository:

| Location | Role | Effect of the change |
|----------|------|----------------------|
| `scrapy/utils/serialize.py` | Definition of the encoder | The behavior is changed here |
| `scrapy/exporters.py` (`JsonItemExporter`, `JsonLinesItemExporter`) | Instantiate the encoder for JSON feeds | Feed date/time output becomes ISO 8601 |
| `scrapy/extensions/periodic_log.py` | Instantiates the encoder for the periodic log | Logged date/time values become ISO 8601 |

No other module in the repository imports the encoder, so the blast radius is contained to
those consumers and to the tests that assert their output.

## Existing behavioural contracts observed in the codebase

- The JSON item exporters build the encoder with keyword arguments pass-through, so any
  encoder-level defaults must remain compatible with `sort_keys`/`indent` usage.
- The periodic log compares a start timestamp with a current timestamp as strings; ISO 8601
  strings for the same clock remain ordered, so the change does not introduce a false
  negative there.
- Existing tests assert the previous space-separated `datetime` format for both the encoder
  itself and the JSON exporters, so those expectations necessarily change with this feature.
