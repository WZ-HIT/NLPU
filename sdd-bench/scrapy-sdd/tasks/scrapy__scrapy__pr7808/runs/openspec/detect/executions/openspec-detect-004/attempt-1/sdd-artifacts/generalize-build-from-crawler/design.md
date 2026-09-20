## Context

See `proposal.md` - Why. `scrapy/utils/misc.py` defines `build_from_crawler()`
with a `SupportsFromCrawler` protocol and overloads; many modules already use
it. The remaining direct calls are in `scrapy/crawler.py`
(`LOG_FORMATTER`, `ExtensionManager`), `scrapy/core/scraper.py`
(`SpiderMiddlewareManager`, `ITEM_PROCESSOR`),
`scrapy/core/downloader/__init__.py` (`DownloaderMiddlewareManager`),
`scrapy/downloadermiddlewares/robotstxt.py` (`ROBOTSTXT_PARSER`), and
`MailSender` construction in `scrapy/extensions/memusage.py` and
`scrapy/extensions/statsmailer.py`. `scrapy/crawler.py` (`STATS_CLASS`) and
`scrapy/core/engine.py` (`DOWNLOADER`) call the class directly.

## Goals / Non-Goals

- Goals: one construction contract for crawler-attached components; no
  behavior change for classes that define `from_crawler()`.
- Non-Goals: changing `build_from_crawler()` semantics, deprecating
  `from_crawler()` on components, or altering spider construction
  (`Spider.from_crawler()` stays required because Scrapy's spider contract
  relies on it).

## Decisions

- Call `build_from_crawler(cls, crawler, *args)` at each internal site instead
  of the direct call. `build_from_crawler()` already prefers `from_crawler()`
  and falls back to `__init__()`, and raises `TypeError` when the constructor
  returns `None`, so no new helper is needed.
- Keep passing the crawler as the first positional argument to `__init__()`
  (e.g. `StatsCollector(crawler)`, `Downloader(crawler)`), matching the
  current behavior of those classes.
- Alternative considered: adding `from_crawler()` to each built-in class.
  Rejected because it duplicates machinery and does not help user classes.

## Risks / Trade-offs

- A class whose `__init__()` signature differs from the crawler-first
  convention would now be constructed through `build_from_crawler()` and could
  fail differently → covered by tests for each converted site.
- `ROBOTSTXT_PARSER` uses `from_crawler(crawler, body)` rather than taking the
  crawler in `__init__()` → the conversion must forward the body argument
  explicitly.

## Migration Plan

Internal-only change released with the next version; no user migration is
required.
