# Quickstart Validation: Log Formatter Dict Interpolation Deprecation

> Tests must not be run during the planning stage. These are the scenarios the
> implementation phase will execute.

## Prerequisites

- Scrapy development environment installed from the repository.
- `pytest` available in the environment.

## Scenario 1: Legacy dict interpolation still renders and warns

Adapter input:

```python
{"level": logging.INFO, "msg": "Crawled %(status)s", "status": 200}
```

Expected: the captured record message is `Crawled 200` and a Scrapy deprecation
warning is recorded.

## Scenario 2: Explicit mapping args do not warn

Adapter input:

```python
{"level": logging.INFO, "msg": "%(pct)d%% done", "args": {"pct": 90}}
```

Expected: `90% done`, no deprecation warning.

## Scenario 3: Explicit tuple args do not warn

Adapter input:

```python
{"level": logging.INFO, "msg": "%d%% done", "args": (90,)}
```

Expected: `90% done`, no deprecation warning.

## Scenario 4: Placeholder-free legacy message is unchanged

Adapter input:

```python
{"level": logging.INFO, "msg": "90% done"}
```

Expected: `90% done`, no deprecation warning, no formatting error.

## Scenario 5: Suppression is unaffected

Crawl with a formatter whose methods return `None` for crawled, scraped, and
dropped results.

Expected: none of those messages appear in the captured logs.

## Focused test entry points

```bash
pytest tests/test_utils_log.py -k LogformatterAdapter
pytest tests/test_logformatter.py
```
