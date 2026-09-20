## Purpose

Defines how Scrapy adapts message and argument values returned by
`LogFormatter` methods while preserving compatibility during migration.

## ADDED Requirements

### Requirement: Dictionary arguments remain compatible but are deprecated

When a `LogFormatter` result contains a dictionary in `args`, Scrapy SHALL
interpolate `msg` with that dictionary and SHALL emit a
`ScrapyDeprecationWarning`.

#### Scenario: Dictionary arguments are returned

- **WHEN** a formatter returns `msg` with mapping-style placeholders and a
  dictionary in `args`
- **THEN** the resulting log message SHALL contain the interpolated values
- **AND** a `ScrapyDeprecationWarning` SHALL be emitted

### Requirement: Tuple arguments use lazy logging

When a `LogFormatter` result contains a tuple in `args`, Scrapy SHALL pass the
message and tuple to the logging call without eagerly interpolating it.

#### Scenario: Tuple arguments are returned

- **WHEN** a formatter returns a message and a non-empty tuple in `args`
- **THEN** logging SHALL receive the message and the tuple elements as separate
  arguments

### Requirement: Empty arguments do not trigger interpolation

When `args` is absent, `None`, an empty dictionary, or an empty tuple, Scrapy
SHALL log the message unchanged and SHALL NOT emit a deprecation warning.

#### Scenario: Empty arguments are returned

- **WHEN** a formatter returns a message containing a literal percent sign and
  empty `args`
- **THEN** the message SHALL be logged unchanged
- **AND** no deprecation warning SHALL be emitted
