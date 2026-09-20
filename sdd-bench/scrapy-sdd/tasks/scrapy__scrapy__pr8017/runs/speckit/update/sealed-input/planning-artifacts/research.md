# Research: Typing the Remaining Exempt Test Modules

## Decision: Treat the current `pyproject.toml` override as the exact scope

**Rationale**: The base commit lists 14 modules under the final `check_untyped_defs = false` override. The PR title describes these as the last modules affected by that setting.

**Alternatives considered**: Searching for all untyped test functions was rejected because strict mode intentionally permits untyped definitions elsewhere through `allow_untyped_defs = true`.

## Decision: Use file-level candidates for package modules

**Rationale**: Mypy targets package modules such as `tests.test_cmdline`, while test selection needs concrete repository-relative files. The collectible module files are `tests/test_cmdline/__init__.py` and `tests/test_settings/__init__.py`.

**Alternatives considered**: Listing package directories was rejected because the requested draft requires test paths and symbols that can be mapped to test execution.

## Decision: Prefer precise annotations, with local escapes only for dynamic boundaries

**Rationale**: Strict mypy exposes errors in mock-heavy and third-party integration code. Narrow annotations preserve useful checking; `cast`, `Any`, or protocol-appropriate adjustments should be limited to boundaries that cannot be modeled safely.

**Alternatives considered**: Weakening global mypy settings was rejected because the feature's purpose is to remove the exception, not broaden it.

## Decision: Validate type checking and test behavior separately

**Rationale**: `mypy scrapy tests` proves the compatibility change, while focused pytest runs and collection checks prove that annotations did not alter runtime behavior or test discovery.

**Alternatives considered**: Relying only on mypy was rejected because static success alone cannot detect runtime test changes.

## Planned Validation Commands

These commands are for the later implementation phase and were not run during planning:

```bash
mypy scrapy tests
pytest tests/test_cmdline tests/test_downloaderslotssettings.py tests/test_dupefilters.py \
  tests/test_extension_statsmailer.py tests/test_extension_throttle.py \
  tests/test_linkextractors.py tests/test_logformatter.py tests/test_mail.py \
  tests/test_pqueues.py tests/test_scheduler_base.py tests/test_settings \
  tests/test_squeues.py tests/test_squeues_request.py tests/test_stats.py
```
