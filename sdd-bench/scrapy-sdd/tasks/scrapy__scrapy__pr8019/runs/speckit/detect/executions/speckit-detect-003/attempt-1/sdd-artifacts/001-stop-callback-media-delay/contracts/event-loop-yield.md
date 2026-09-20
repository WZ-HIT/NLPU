# Contract: Internal Event-Loop Yield

Scope: internal contract between `scrapy.utils.defer` and its call sites. Private
helper; not part of the public Scrapy API.

## Provider

```text
scrapy.utils.defer._process_pending_io() -> Awaitable[None]
```

## Guarantees

1. It yields control to the event loop without a fixed delay.
2. On resume, callbacks of reader/writer events that were ready when the yield began
   have been given the opportunity to run (achieved by yielding twice).
3. It works with the asyncio reactor and with the Twisted-only reactor.
4. It never raises under normal operation and performs no I/O of its own.

## Consumers and their obligations

| Consumer | Obligation |
|----------|-----------|
| `scrapy.core.scraper.Scraper.call_spider_async()` | Call the yield before invoking the callback/errback |
| `scrapy.core.spidermw.SpiderMiddlewareManager.scrape_response_async()` | Call the yield before processing a raised exception |
| `scrapy.core.downloader.middleware.DownloaderMiddlewareManager.download_async()` | Call the yield before processing a raised exception |
| `scrapy.core.downloader.Downloader._download()` | Call the yield before re-raising a download failure; slot cleanup and `request_left_downloader` still happen |
| `scrapy.pipelines.media.MediaPipeline._process_request()` | Call the yield on the cached-result path, before starting a download, and after obtaining the result but before caching it |

## Media waiter notification contract

- `MediaPipeline._cache_result_and_execute_waiters()` stores exactly one result per
  fingerprint and resolves every waiter in `waiting.pop(fingerprint)` using
  `wad.callback(result)` for successes and `wad.errback(result)` for failures.
- No per-waiter `call_later(...)` delay is used.
- Cached failures still raise through the request errback when one is set.

## Out of scope / unchanged contracts

- Public deprecated helpers `defer_fail()`, `defer_succeed()`, `defer_result()` keep
  their fixed delay and `ScrapyDeprecationWarning`.
- No public API, setting, or signal is added, removed or renamed.
