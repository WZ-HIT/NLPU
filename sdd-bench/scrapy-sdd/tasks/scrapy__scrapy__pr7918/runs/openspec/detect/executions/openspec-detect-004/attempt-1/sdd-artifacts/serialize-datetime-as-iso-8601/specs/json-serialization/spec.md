## Purpose

Defines a stable, standard JSON representation for Python date and time values
serialized by Scrapy.

## ADDED Requirements

### Requirement: ISO 8601 serialization of temporal values

Scrapy SHALL serialize `datetime.datetime`, `datetime.date`, and
`datetime.time` values to JSON strings using their ISO 8601 representations.

#### Scenario: Serialize a naive datetime

- **WHEN** a JSON value contains `datetime.datetime(2010, 1, 2, 10, 11, 12)`
- **THEN** it is serialized as `"2010-01-02T10:11:12"`

#### Scenario: Serialize a date

- **WHEN** a JSON value contains `datetime.date(2010, 1, 2)`
- **THEN** it is serialized as `"2010-01-02"`

#### Scenario: Serialize a time

- **WHEN** a JSON value contains `datetime.time(10, 11, 12)`
- **THEN** it is serialized as `"10:11:12"`

#### Scenario: Preserve timezone and subsecond information

- **WHEN** a JSON value contains an aware datetime with microseconds and a UTC offset
- **THEN** the serialized string includes the microseconds and offset
