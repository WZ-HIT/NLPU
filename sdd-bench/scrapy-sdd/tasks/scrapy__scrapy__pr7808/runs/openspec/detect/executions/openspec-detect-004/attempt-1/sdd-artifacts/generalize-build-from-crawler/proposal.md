## Why

Scrapy already exposes :func:`scrapy.utils.misc.build_from_crawler` and uses it
for many components (request fingerprinter, download handlers, scheduler,
dupefilter, queues, middleware entries, add-ons, feed storage), so that
configured classes may define either ``from_crawler()`` or a plain
``__init__()``. Several internal construction paths still call
``from_crawler()`` directly (or instantiate a class directly), which forces
users to provide ``from_crawler()`` for those components and makes the
supported construction contract inconsistent.

## What Changes

- Replace direct ``from_crawler()`` calls made by Scrapy internals with
  ``build_from_crawler()``:
  - ``LOG_FORMATTER`` (``scrapy/crawler.py``, ``lf_cls.from_crawler(self)``)
  - ``ITEM_PROCESSOR`` and the spider middleware manager
    (``scrapy/core/scraper.py``)
  - downloader middleware manager
    (``scrapy/core/downloader/__init__.py``)
  - ``ROBOTSTXT_PARSER`` (``scrapy/downloadermiddlewares/robotstxt.py``)
  - ``MailSender`` in ``scrapy/extensions/memusage.py`` and
    ``scrapy/extensions/statsmailer.py``
  - extension manager (``scrapy/crawler.py``)
- Use ``build_from_crawler()`` for internally instantiated configurable
  classes that currently call the constructor directly
  (``STATS_CLASS`` in ``scrapy/crawler.py``, ``DOWNLOADER`` in
  ``scrapy/core/engine.py``), so a ``from_crawler()`` defined by a user class
  is honored.
- No public API removal; behavior is unchanged for every class that already
  defines ``from_crawler()``.

## Capabilities

### New Capabilities

- `component-construction`: Defines how Scrapy constructs configurable
  components (crawler-attached objects built from settings), including which
  constructors are accepted.

### Modified Capabilities

- None.

## Impact

- Code: ``scrapy/crawler.py``, ``scrapy/core/scraper.py``,
  ``scrapy/core/downloader/__init__.py``, ``scrapy/core/engine.py``,
  ``scrapy/downloadermiddlewares/robotstxt.py``,
  ``scrapy/extensions/memusage.py``, ``scrapy/extensions/statsmailer.py``.
- Docs: ``docs/topics/components.rst`` (component construction contract),
  release notes.
- Tests: crawler, log formatter, middleware, scraper, downloader, robotstxt,
  stats, mail and stats-mailer/memusage test suites exercise these construction
  paths.
