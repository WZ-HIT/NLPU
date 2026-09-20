# Data Model: CI Warnings as Errors

## Warning Policy

| Field | Description |
| --- | --- |
| Base action | `error` for all otherwise-unhandled warnings |
| Exceptions | Ordered filters for known warning classes/messages |
| Scope | Global pytest configuration and inherited tox environments |

## Warning Exception

| Field | Description |
| --- | --- |
| Category | Warning class, when constrained |
| Message/module | Narrow matcher, when constrained |
| Reason | External bug, intentional deprecation, or infrastructure warning |
| Owner | Config, test module, or individual test |

## Affected Test

| Field | Description |
| --- | --- |
| Path | Repository-relative test path |
| Symbols | Test functions, methods, or classes exercising the behavior |
| Reason | Why the test is likely to emit or assert a warning |

## Validation

An intentional warning passes when captured. An unhandled warning fails. A
scoped exception passes only for its documented warning.
