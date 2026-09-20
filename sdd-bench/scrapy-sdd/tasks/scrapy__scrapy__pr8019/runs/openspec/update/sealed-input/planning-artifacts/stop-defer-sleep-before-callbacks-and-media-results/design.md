## Context

See proposal.md - Why. `scrapy/utils/defer.py` exposes the private helper `_defer_sleep_async()`, which awaits `sleep(_DEFER_DELAY)` with `_DEFER_DELAY = 0.1`. It is called before spider callback dispatch (`scrapy/core/scraper.py`), in spider middleware and downloader middleware exception handling (`scrapy/core/spidermw.py`, `scrapy/core/downloader/middleware.py`), in downloader slot handling (`scrapy/core/downloader/__init__.py`), and twice in the media pipeline (`scrapy/pipelines/media.py`). `MediaPipeline._cache_result_and_execute_waiters()` additionally resolves waiting deferreds through `call_later(_DEFER_DELAY, ...)`.

The delay exists to give the reactor event loop a chance to go through readers and writers before attending pending delayed calls. `scrapy.utils.asyncio.sleep()` already abstracts the asyncio and Twisted implementations, so any replacement must work with both reactors.

## Goals / Non-Goals

**Goals:**

- Keep the ordering guarantee (callbacks and media results are delivered after pending I/O is processed) while removing the fixed 100 ms cost.
- Keep one private helper used by every previously affected call site, so the guarantee is implemented once.

**Non-Goals:**

- Changing public APIs, settings, or signals.
- Changing the deprecated `defer_fail()`/`defer_succeed()`/`defer_result()` helpers, which keep using `_DEFER_DELAY`.
- Rewriting the downloader, scraper, or media pipeline scheduling model.

## Decisions

- **Replace the fixed sleep with two zero-second yields.** Yielding once can resume before the callbacks of file descriptors that the poll reported ready; a second yield is what makes it certain that those callbacks have run. Chosen over `reactor.callLater(0)` because it works with both the Twisted and asyncio reactors through the existing `sleep()` helper, and over a smaller non-zero delay because any wall-clock delay still costs per request.
- **Rename the helper to reflect what it guarantees.** `_defer_sleep_async` becomes a name that describes processing pending I/O, so call sites no longer read as intentional sleeps. Private name, so no deprecation path is needed.
- **Resolve media waiters directly.** `_cache_result_and_execute_waiters()` calls the waiting deferreds immediately and relies on the surrounding I/O yield for ordering, instead of scheduling each resolution with `call_later(_DEFER_DELAY, ...)`. This also removes the per-waiter delay and the dependency of the media pipeline on the delay constant.
- **Add one I/O yield before caching media results.** The pipeline yields once more after the download finishes and before caching, so the result is published with the same ordering guarantee as before.

## Risks / Trade-offs

- **Ordering regressions:** if two zero-second yields are not enough under a reactor, callbacks could observe incomplete I/O. Mitigation: keep the yield helper centralized and cover callback and media paths with existing engine/pipeline tests.
- **Timing-sensitive tests:** tests that implicitly relied on the 100 ms spacing may change behavior or become flaky. Mitigation: run the affected suites and inspect tests that import the removed helper.
- **Private-symbol rename:** third-party code importing `_defer_sleep_async` breaks, but the symbol is private and undocumented.
