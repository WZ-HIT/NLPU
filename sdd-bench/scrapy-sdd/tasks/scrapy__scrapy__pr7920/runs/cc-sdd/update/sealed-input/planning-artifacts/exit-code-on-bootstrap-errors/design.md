# Design: Exit code 1 on crawler bootstrap errors

## Summary

Reuse the existing bootstrap-failure signal already exposed by the crawler
processes instead of adding new error plumbing.

## Mechanism

`CrawlerRunnerBase` / `AsyncCrawlerProcess` set `bootstrap_failed` when a
crawler could not be created or its start failed. `scrapy/commands/crawl.py`
and `scrapy/commands/runspider.py` already do:

```python
self.crawler_process.start()
if self.crawler_process.bootstrap_failed:
    self.exitcode = 1
```

`scrapy/cmdline.py` then exits with `sys.exit(cmd.exitcode)`.

## File structure plan

- `scrapy/commands/check.py` — after `crawler_process.start()`, fold
  `bootstrap_failed` into the existing `exitcode` computation so that both
  contract failures and bootstrap failures yield 1.
- `scrapy/commands/fetch.py` — set `self.exitcode = 1` when
  `bootstrap_failed` after the process start.
- `scrapy/commands/parse.py` — set `self.exitcode = 1` when the crawler
  bootstrap failed (spider missing / response never produced).
- Tests for the above live in the per-command test modules.

## Boundaries

No public API changes; the commands only adjust their own `exitcode`. Shared
base classes are not modified, so other commands keep their current behaviour.

## Test strategy

Command-level subprocess tests (`tests.utils.cmdline.proc`) assert the process
return code for both the failure and the success paths.
