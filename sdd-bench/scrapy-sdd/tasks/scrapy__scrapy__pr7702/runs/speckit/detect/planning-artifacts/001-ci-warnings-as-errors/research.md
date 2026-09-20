# Phase 0 Research: CI Warnings as Errors

## Decision

Add `error` as the first global pytest warning filter and retain only explicit
exceptions for expected third-party, intentional, or unraisable warnings.

## Rationale

Pytest processes later filters before earlier ones, so a global `error` base
filter makes unhandled warnings fail while allowing local markers and
`pytest.warns` blocks to override it deliberately. This applies consistently to
all tox environments.

## Alternatives considered

- Apply errors only to "latest" environments. Rejected because it leaves older
  dependency combinations unguarded and complicates the CI matrix.
- Add `-W error` only in individual tox commands. Rejected because it is easy
  to omit and does not cover collection consistently.
- Fix every warning globally without exceptions. Rejected because some warning
  tests intentionally trigger deprecated behavior and some warnings originate
  in dependencies.

## Repository evidence

- `pyproject.toml` owns pytest's global warning filters.
- The tox suites all invoke pytest against `scrapy` and `tests`.
- Tests already use `pytest.warns`, `pytest.mark.filterwarnings`, and
  `warnings.catch_warnings` for expected warning behavior.
