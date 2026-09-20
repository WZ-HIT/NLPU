## Context

See `proposal.md` - Why. The project uses mypy in strict mode, with a temporary per-module override that disables `check_untyped_defs` for selected test modules. Seven spider-related entries remain in that override.

## Goals / Non-Goals

**Goals:**

- Add complete, accurate annotations to the seven spider-related test modules.
- Keep the annotations compatible with Python 3.10+ and the project's existing `from __future__ import annotations` convention.
- Remove the seven modules from the temporary mypy override.

**Non-Goals:**

- Changing Scrapy runtime code or spider behavior.
- Refactoring tests beyond what is needed to satisfy mypy.
- Typing unrelated modules from the same temporary override.

## Decisions

- Annotate test methods and helpers using `None`, `Any`, Scrapy response/request types, and existing test utility protocols as appropriate.
- Prefer narrow annotations where the runtime contract is clear; use `Any` only at intentionally dynamic test boundaries.
- Keep `pyproject.toml` entries for unrelated modules in the temporary override.

## Risks / Trade-offs

- Overly broad `Any` annotations could hide real typing errors. Mitigation: use `reveal_type`-safe, concrete types where available and run the focused mypy environment.
- Fixture and callback signatures can be dynamic. Mitigation: mirror the signatures expected by Scrapy's public spider interfaces and existing typed tests.
