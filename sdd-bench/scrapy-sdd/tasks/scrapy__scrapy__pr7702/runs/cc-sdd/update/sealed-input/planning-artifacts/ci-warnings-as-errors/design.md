# Design: CI warnings to errors (planning)

## Change shape

The change is configuration-first, with test follow-up:

1. `pyproject.toml` — prepend `"error"` to `[tool.pytest.ini_options].filterwarnings`, keeping the existing three ignores (`twisted.web.static` DeprecationWarning, `pytest_cov.CovDisabledWarning`, the Twisted unclosed-socket `PytestUnraisableExceptionWarning`).
2. `tox.ini` / CI workflows — keep a single global policy instead of per-environment toggles.
3. `tests/` and `conftest.py` — scope or assert warnings that the new policy turns fatal.

## Warning sources that the policy exposes

Warning emission sites in `scrapy/` fall into a few groups, and each group maps to test files:

- Deprecated settings (`DNS_RESOLVER`, `CONCURRENT_REQUESTS_PER_IP`) in `scrapy/settings/__init__.py` and `scrapy/settings/default_settings.py`.
- Deprecated spider attributes and `Crawler.stop()`, `DNS_RESOLVER` in `scrapy/crawler.py`.
- Deprecated middleware/engine/scraper sync entry points (`scrapy/middleware.py`, `scrapy/core/engine.py`, `scrapy/core/scraper.py`, `scrapy/core/downloader/handlers/__init__.py`).
- Deprecated helper functions (`scrapy/utils/defer.py`, `scrapy/utils/misc.py`, `scrapy/utils/ssl.py`, `scrapy/utils/sitemap.py`).
- Deprecated modules warning at import time (`scrapy/mail.py`, `scrapy/interfaces.py`, `scrapy/extensions/statsmailer.py`, `scrapy/core/downloader/handlers/http.py`; the last four are excluded from `--doctest-modules` collection by `tests/ignores.txt`).
- Non-deprecation warnings: duplicate spider names (`UserWarning`) and `warn_only` imports (`RuntimeWarning`) in `scrapy/spiderloader.py`, generator-return warnings in `scrapy/utils/misc.py`, invalid referrer policies (`RuntimeWarning`) in `scrapy/spidermiddlewares/referer.py`.

## Detection strategy

Because the stage is read-only and test execution is forbidden, candidate tests are located statically:

1. Find every `warnings.warn(...)` site under `scrapy/` and classify the warning category and trigger condition.
2. Find test files that (a) already suppress or assert those warnings, or (b) reach the trigger without suppression.
3. Rank by proximity to the trigger: dedicated deprecation-warning tests first, then shared test bases that other modules inherit.

## Risk and mitigation

- Risk: blunt `ignore` filters hide real regressions. Mitigation: keep filters message- and module-scoped, as the existing three already are.
- Risk: removed deprecation coverage. Mitigation: replace reliance on non-fatal warnings with explicit `pytest.warns`/`recwarn` assertions.
