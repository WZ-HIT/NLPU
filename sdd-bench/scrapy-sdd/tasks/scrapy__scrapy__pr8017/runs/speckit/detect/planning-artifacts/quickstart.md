# Quickstart Validation: Typing the Remaining Exempt Test Modules

This guide describes validation for the later implementation phase. No commands were run during the planning-only task.

## Prerequisites

- Install the repository's pinned mypy environment described in `tox.ini`.
- Start from base commit `1420418c813ed01af78da62bc4a6e60bb4a7403b` plus the implementation changes.
- Keep `pyproject.toml` and the 14 candidate test files as the change boundary.

## Validate Mypy Coverage

1. Confirm the override no longer disables `check_untyped_defs` for any `tests.*` module.
2. Run `mypy scrapy tests`.
3. Expect zero errors.

## Validate Test Behavior

Run the focused suite:

```bash
pytest tests/test_cmdline tests/test_downloaderslotssettings.py tests/test_dupefilters.py \
  tests/test_extension_statsmailer.py tests/test_extension_throttle.py \
  tests/test_linkextractors.py tests/test_logformatter.py tests/test_mail.py \
  tests/test_pqueues.py tests/test_scheduler_base.py tests/test_settings \
  tests/test_squeues.py tests/test_squeues_request.py tests/test_stats.py
```

Expected outcome: the same tests collect and pass as on the base revision.

## Review Checks

- Confirm no production source files changed.
- Confirm every removed module entry corresponds to a typed candidate file.
- Confirm annotations remain valid on Python 3.10.
- Confirm no new `type: ignore` comments were added unless a dependency boundary makes one unavoidable and justified.
