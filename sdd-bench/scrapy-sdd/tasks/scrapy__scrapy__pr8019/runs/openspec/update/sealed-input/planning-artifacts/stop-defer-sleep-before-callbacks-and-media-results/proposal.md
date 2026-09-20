## Why

Scrapy inserts a fixed 100 ms sleep before invoking spider callbacks, before producing media-pipeline download results, and before several other deferred code paths. Every crawled request and every media download therefore pays at least 100 ms of pure latency, which dominates short crawls and slows the test suite.

## What Changes

- Replace the fixed-delay helper (`scrapy.utils.defer._defer_sleep_async`, which awaited `sleep(_DEFER_DELAY)` with `_DEFER_DELAY = 0.1`) with a bounded event-loop yield helper that hands control back to the event loop twice, so pending reader/writer callbacks are processed without adding wall-clock delay.
- Update every call site of the old helper: spider callback dispatch, spider middleware exception handling, downloader middleware exception handling, downloader slot handling, and the media pipeline.
- Stop delaying media-pipeline waiters: when a media request completes, waiting deferreds are resolved with the cached result immediately instead of through a 100 ms `call_later()`.
- Preserve the existing ordering guarantee: callbacks and media results are still delivered only after the event loop has processed pending I/O.
- No public API is removed; the affected helper is private. The deprecated `defer_fail()`/`defer_succeed()`/`defer_result()` helpers keep their existing delay.

## Capabilities

### New Capabilities

- `core/callback-scheduling`: the ordering contract for invoking spider callbacks and delivering media-pipeline results, namely that they run after pending event-loop I/O is processed and are not delayed by a fixed amount of time.

### Modified Capabilities

None. No existing requirement in `openspec/specs/` changes; the repository has no capability specs yet.

## Impact

Affected code: `scrapy/utils/defer.py`, `scrapy/core/scraper.py`, `scrapy/core/spidermw.py`, `scrapy/core/downloader/__init__.py`, `scrapy/core/downloader/middleware.py`, `scrapy/pipelines/media.py`.

Affected tests: any test that exercises spider callback dispatch, downloader/spider middleware exception handling, media result caching and waiters, or imports the private helper directly.

Observable impact: crawls and media downloads finish sooner; ordering of callbacks relative to pending I/O is unchanged. No settings, signals, or public APIs change.
