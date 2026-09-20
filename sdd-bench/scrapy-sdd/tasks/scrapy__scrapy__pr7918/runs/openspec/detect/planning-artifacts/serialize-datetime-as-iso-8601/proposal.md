## Why

`ScrapyJSONEncoder` currently emits dates and times in a space-separated,
locale-independent but non-ISO-8601 form, and omits `datetime` timezone and
microsecond information. This produces incomplete representations for
downstream consumers and makes JSON output inconsistent with Python's standard
ISO 8601 representation.

## What Changes

- Serialize `datetime.datetime` values using ISO 8601, including a `T`
  separator, microseconds when present, and any UTC offset.
- Serialize `datetime.date` and `datetime.time` values using their ISO 8601
  representations, preserving date-only and time-only output.
- Keep the change limited to JSON serialization; exporters that stringify
  values independently, such as CSV and XML, keep their existing behavior.

## Capabilities

### New Capabilities

- `json-serialization`: Defines the JSON representation of Python date and time
  values emitted by Scrapy.

### Modified Capabilities

None.

## Impact

Affected code: `scrapy/utils/serialize.py`. JSON and JSON Lines item exporters,
feed exports, and periodic logging that use `ScrapyJSONEncoder` will emit the
new temporal representations. Existing JSON consumers that require the legacy
space-separated format will need to adapt.
