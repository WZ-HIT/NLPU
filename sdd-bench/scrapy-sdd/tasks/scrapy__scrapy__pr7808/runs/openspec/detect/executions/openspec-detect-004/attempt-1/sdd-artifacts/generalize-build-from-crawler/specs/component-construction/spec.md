## Purpose

Defines how Scrapy builds the configurable components that are attached to a
``Crawler``, so that component classes can rely on a single, consistent
construction contract.

## ADDED Requirements

### Requirement: Components may be built from either constructor

When Scrapy builds a component from settings or from internal wiring,
it SHALL use :func:`scrapy.utils.misc.build_from_crawler`, which SHALL call the
component's ``from_crawler()`` class method when one is defined and otherwise
SHALL call the component's ``__init__()``.

#### Scenario: Component defines from_crawler

- **WHEN** a configured component class defines ``from_crawler(crawler, *args, **kwargs)``
- **THEN** Scrapy builds the instance by calling that ``from_crawler()`` with the crawler and any extra arguments

#### Scenario: Component defines only __init__

- **WHEN** a configured component class does not define ``from_crawler()``
- **THEN** Scrapy builds the instance by calling its ``__init__()`` with the extra arguments

### Requirement: Internal construction paths are consistent

The components that Scrapy builds internally SHALL use the same construction
contract as components built from component dictionaries, so that no
internally built component requires a ``from_crawler()`` method that its
public counterpart does not require.

#### Scenario: Plain log formatter class

- **WHEN** ``LOG_FORMATTER`` points to a class that only defines ``__init__(self, crawler)``
- **THEN** the crawler is created successfully and ``crawler.logformatter`` is an instance of that class

#### Scenario: Plain stats class

- **WHEN** ``STATS_CLASS`` points to a class that only defines ``__init__(self, crawler)``
- **THEN** the crawler is created successfully and ``crawler.stats`` is an instance of that class

#### Scenario: Plain item processor class

- **WHEN** ``ITEM_PROCESSOR`` points to a class that only defines ``__init__(self, crawler)``
- **THEN** the scraper instantiates that class instead of failing with ``AttributeError``
