# Feature Specification: ISO 8601 Date and Time Serialization in ScrapyJSONEncoder

**Feature Branch**: `001-json-iso8601-datetimes`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "Serialize dates and times as ISO 8601 in ScrapyJSONEncoder (scrapy/scrapy PR #7918, resolves issue #2087)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Parseable date/time values in JSON output (Priority: P1)

A user scrapes items containing `datetime`, `date`, or `time` values and exports them to a
JSON or JSON Lines feed (or any code path that uses the project's JSON encoder). Today the
emitted strings use ad-hoc formats (`"2010-01-02 10:11:12"`), which are not ISO 8601 and
cannot be handed to standard parsers. The user needs those values emitted in the
internationally recognized ISO 8601 form so that downstream consumers can parse them
without custom string handling.

**Why this priority**: This is the entire purpose of the change. It is the only user-visible
behavior difference and it is what the linked issue (#2087) asks for.

**Independent Test**: Serialize one `datetime`, one `date`, and one `time` value through the
project's JSON encoder and confirm the produced strings parse back with a standard ISO 8601
parser; confirm a JSON Lines export of the same item contains the ISO 8601 strings.

**Acceptance Scenarios**:

1. **Given** an item field holding `datetime(2010, 1, 2, 10, 11, 12)`, **When** it is exported to a JSON/JSON Lines feed, **Then** the value is the string `"2010-01-02T10:11:12"` (the date and time components separated by `T`).
2. **Given** an item field holding `date(2010, 1, 2)`, **When** it is exported, **Then** the value is the string `"2010-01-02"`.
3. **Given** an item field holding `time(10, 11, 12)`, **When** it is exported, **Then** the value is the string `"10:11:12"`.
4. **Given** a timezone-aware `datetime`, **When** it is exported, **Then** the UTC offset is preserved in the emitted string.
5. **Given** a `datetime` carrying microseconds, **When** it is exported, **Then** the sub-second component is preserved.

---

### User Story 2 - Unambiguous time values in periodic log output (Priority: P2)

An operator reads the JSON emitted by the periodic log extension. When the log includes
timing or stats containing date/time values, those values should use the same ISO 8601 form
so that they are unambiguous and machine-readable.

**Why this priority**: It is the same serialization path applied to a second consumer; it
delivers value but is not the primary complaint.

**Independent Test**: Emit a periodic log record that contains timing information and confirm
the emitted JSON's date/time values parse as ISO 8601.

**Acceptance Scenarios**:

1. **Given** the periodic log extension emits timing or stats JSON, **When** a date/time value is included, **Then** it is emitted in ISO 8601 form.

---

### User Story 3 - Round-trip safety for consumers (Priority: P3)

A consumer of the exported JSON reads a date/time string and converts it back to a native
date/time value. The user needs that conversion to be lossless for the components the source
value carried (date, time, sub-second precision, UTC offset).

**Why this priority**: It is a quality attribute of User Story 1 rather than a separate flow,
but it is the reason ISO 8601 is requested instead of another bespoke format.

**Independent Test**: Serialize a value, parse the result with a standard ISO 8601 parser, and
compare it to the original value.

**Acceptance Scenarios**:

1. **Given** a serialized timezone-aware `datetime` with microseconds, **When** it is parsed back with a standard ISO 8601 parser, **Then** the reconstructed value equals the original value.

---

### Edge Cases

- A `datetime` value is also an instance of `date`; the more specific handling must win, otherwise a `datetime` would lose its time component.
- Timezone-aware values must keep their offset; timezone-naive values must remain naive (no offset invented).
- Values with zero microseconds and values with microseconds must both be valid ISO 8601.
- A `time` value with `tzinfo` must keep its offset; a `time` value without `tzinfo` must not gain one.
- Non-date/time inputs already handled by the encoder (sets, decimals, deferreds, requests, responses, items) must keep their current behavior.
- Subclasses of `datetime` (for example a pandas timestamp-like value) must follow the date/time branch, not fall through to the generic object handling.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The project's JSON encoder MUST serialize `datetime` values as ISO 8601 date-and-time strings, using `T` as the separator between date and time.
- **FR-002**: The JSON encoder MUST serialize `date` values as ISO 8601 calendar-date strings (`YYYY-MM-DD`).
- **FR-003**: The JSON encoder MUST serialize `time` values as ISO 8601 clock-time strings, preserving sub-second precision and any UTC offset present.
- **FR-004**: The JSON encoder MUST preserve microsecond precision for date/time values that carry it and MUST NOT emit a spurious fractional part for values that do not.
- **FR-005**: The JSON encoder MUST preserve the UTC offset for timezone-aware values and MUST NOT introduce an offset for naive values.
- **FR-006**: The JSON encoder MUST continue to serialize all other supported types (sets, decimals, deferreds, requests, responses, and items) exactly as before.
- **FR-007**: JSON and JSON Lines item exporters MUST reflect the new date/time format, since they delegate to the JSON encoder.
- **FR-008**: The periodic log extension's JSON output MUST reflect the new date/time format, since it delegates to the JSON encoder.
- **FR-009**: The change MUST NOT add a new runtime dependency and MUST NOT change the encoder's public import path or class name.
- **FR-010**: The existing configuration surface of the encoder (keyword arguments passed through from the exporters, e.g. `sort_keys`, `indent`) MUST keep working unchanged. The previous format-holding class attributes on the encoder MUST no longer be required for date/time output.

### Key Entities *(include if feature involves data)*

- **ScrapyJSONEncoder**: The JSON encoder subclass that defines how non-JSON-native Python values are converted to JSON-compatible values; owns the date/time conversion behavior.
- **DateTime value**: A `datetime`, `date`, or `time` instance stored in an item or stats entry; the input to the conversion behavior.
- **JSON export consumer**: The JSON and JSON Lines item exporters used by feeds; delegate serialization to the encoder.
- **Periodic log consumer**: The periodic log extension; serializes timing and stats dictionaries with the encoder.
- **Serialized temporal string**: The ISO 8601 text form emitted in place of a temporal value; must be parseable by standard ISO 8601 parsers.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of exported `datetime`, `date`, and `time` values emitted by the encoder are accepted by a standard ISO 8601 parser.
- **SC-002**: A `datetime` with a `T`-separated date and time is produced for every exported `datetime` value (0 exports still use a space as the date/time separator).
- **SC-003**: Round-tripping a timezone-aware `datetime` with microseconds through export and standard parsing returns a value equal to the original in 100% of cases.
- **SC-004**: 0 regressions in the existing serialization behavior for non-temporal types (sets, decimals, deferreds, requests, responses, items).
- **SC-005**: The JSON Lines export and the periodic log JSON output both show the ISO 8601 form for temporal values in 100% of observed cases.

## Assumptions

- The repository targets a Python version whose standard library `datetime` objects provide an ISO 8601 representation (`isoformat`), so no third-party date library is introduced.
- "ISO 8601" here means the standard-library representation of the value, including the `T` separator, optional fractional seconds, and optional UTC offset.
- Emitting the offset for timezone-aware values is desirable and does not break the existing consumers, because the emitted value remains a JSON string.
- Consumers that previously string-compared temporal values are out of scope; the change is intentionally a format change to a standards-based representation.
- Behavior for non-temporal types is unchanged, so the change is deliberately narrow.
