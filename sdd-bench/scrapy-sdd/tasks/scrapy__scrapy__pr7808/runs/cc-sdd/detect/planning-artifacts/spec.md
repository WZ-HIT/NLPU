# Detect-stage spec: scrapy/scrapy PR 7808

## Change under study

- Repository: `scrapy/scrapy`
- Base commit: `f1694269d8c9437461936ed449e81aa2ccb3b7cb`
- PR title: `Generalize the use of build_from_crawler() internally`
- PR body: (empty)

## Interpretation

`scrapy.utils.misc.build_from_crawler()` (documented as the constructor of every
Scrapy "component") is already used for many configurable components
(`ADDONS`, `DOWNLOADER_MIDDLEWARES`, `DOWNLOAD_HANDLERS`, `DUPEFILTER_CLASS`,
`EXTENSIONS`, `FEED_*`, `ITEM_PIPELINES`, `SCHEDULER*`, `SPIDER_MIDDLEWARES`,
`TWISTED_DNS_RESOLVER`). The PR generalizes that construction path to the
*internally* built core objects, which today are still created by direct
`Class(...)` calls or direct `Class.from_crawler(...)` calls:

| Site | Current construction | Generalized form |
| --- | --- | --- |
| `scrapy/crawler.py` (`STATS_CLASS`) | `load_object(...)(self)` | `build_from_crawler(...)` |
| `scrapy/crawler.py` (`LOG_FORMATTER`) | `lf_cls.from_crawler(self)` | `build_from_crawler(...)` |
| `scrapy/crawler.py` (`EXTENSIONS`, spider class) | direct `from_crawler()` | `build_from_crawler(...)` |
| `scrapy/core/engine.py` (`DOWNLOADER`) | `downloader_cls(crawler)` | `build_from_crawler(...)` |
| `scrapy/core/scraper.py` (`SPIDER_MIDDLEWARES`, `ITEM_PROCESSOR`) | direct `from_crawler()` | `build_from_crawler(...)` |
| `scrapy/core/downloader/__init__.py` (`DOWNLOADER_MIDDLEWARES`) | direct `from_crawler()` | `build_from_crawler(...)` |
| `scrapy/downloadermiddlewares/robotstxt.py` (`ROBOTSTXT_PARSER`) | `parser.from_crawler(...)` | `build_from_crawler(...)` |
| `scrapy/extensions/statsmailer.py`, `memusage.py` (`MailSender`) | direct `from_crawler()` | `build_from_crawler(...)` |
| `scrapy/spiderloader.py` (`SPIDER_LOADER_CLASS`) | `loader_cls.from_settings(...)` | crawler-based construction |

Behavioural effect (the part tests can pin down): any class assigned to those
settings is built through the same protocol, so an optional `from_crawler()`
classmethod is honoured, a plain `__init__` still works, and a `from_crawler()`
returning `None` raises `TypeError`.

## Detection approach (this stage)

Candidate test files were derived by mapping each construction site above to the
test modules that exercise the corresponding setting/component, then confirming
the relevant symbols (custom `STATS_CLASS`/`LOG_FORMATTER`/`DOWNLOADER`/
`ITEM_PROCESSOR`/`SPIDER_LOADER_CLASS` classes, middleware-manager fixtures,
robots.txt parser fixtures, and the `build_from_crawler()` unit test).

No tests were executed and no project code or tests were modified; this stage
only inspects the read-only workspace and writes planning artifacts.

The single deliverable for the detect phase is `detection-draft.json`
(`candidates` array only).
