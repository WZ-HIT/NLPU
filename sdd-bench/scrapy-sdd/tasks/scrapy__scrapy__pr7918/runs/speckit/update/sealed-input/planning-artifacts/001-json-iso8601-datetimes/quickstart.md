# Quickstart Validation Guide: ISO 8601 Date and Time Serialization

**Feature**: 001-json-iso8601-datetimes

This guide documents how a reviewer validates the feature end to end once implemented. The
commands are listed for the implementation stage; they are **not** executed during this
Detect planning stage.

## Prerequisites

- A checkout of the repository at the feature branch.
- The project's development environment, so the package under test resolves from the working
  copy.

## Scenario 1 — Encoder emits ISO 8601 for temporal values

1. Serialize a naive `datetime`, a `date`, and a `time` through the public encoder.
2. Confirm the `datetime` output uses `T` between date and time, the `date` output is
   `YYYY-MM-DD`, and the `time` output is `HH:MM:SS`.
3. Parse each output with the standard library ISO 8601 parser and confirm it succeeds.

**Expected outcome**: every temporal value serializes to a parseable ISO 8601 string
(SC-001, SC-002).

## Scenario 2 — Precision and offsets survive

1. Serialize a timezone-aware `datetime` that carries microseconds.
2. Confirm the fractional seconds are present.
3. Confirm the UTC offset is present.
4. Parse the result and compare it to the original value.

**Expected outcome**: the round-tripped value equals the original (SC-003).

## Scenario 3 — JSON feed exporters reflect the format

1. Export an item containing a `datetime` to a JSON Lines feed and to a JSON feed.
2. Read the feed back with a JSON parser.
3. Confirm the temporal field is now an ISO 8601 string rather than the previous
   space-separated form.

**Expected outcome**: both feed formats show the ISO 8601 form (SC-005).

## Scenario 4 — Periodic log output reflects the format

1. Emit a periodic log record that includes timing information.
2. Parse the logged message as JSON.
3. Confirm the temporal values parse as ISO 8601.

**Expected outcome**: logged temporal values are ISO 8601 strings (SC-005).

## Scenario 5 — Non-regression for other types

1. Serialize a set, a decimal, a deferred, a request, a response, and an item.
2. Compare against the behavior before the change.

**Expected outcome**: no difference in the serialized output for these types (SC-004).

## Automated validation

The repository's existing test entry points cover these scenarios. The relevant test files
are listed in `tasks.md`; consult `data-model.md` for the authoritative mapping of input type
to serialized string and `contracts/json-serialization-contract.md` for the guarantee
boundary.
