# Spec: Stop sleeping 100 ms before every callback and media result

Planning-only artifact for the cc-sdd Detect stage. No project code or tests were
modified, and no tests were executed.

- Repository: `scrapy/scrapy`
- Pull request: `8019`
- Base commit: `916039ca4ca79ea4ed38e74d71e25c2584c1925e`
- Scope of this stage: (1) spec/detect analysis of the change surface, (2) candidate test-file detection.

## Requested behaviour

Scrapy delays each spider callback and each media-pipeline result by 100 ms through
`scrapy.utils.defer._defer_sleep_async()` (`_DEFER_DELAY = 0.1`). The change removes that
fixed delay and replaces it with a cheap "let the event loop poll readers/writers" yield,
so callbacks and media results are no longer penalised by 100 ms each.

## Change surface (production code, read-only analysis)

| Location | Current code | New behaviour |
| --- | --- | --- |
| `scrapy/utils/defer.py:89` | `_defer_sleep_async()` awaits `sleep(_DEFER_DELAY)` | replaced by `_process_pending_io()` awaiting `sleep(0)` twice |
| `scrapy/core/scraper.py:315` | `await _defer_sleep_async()` before every callback in `Scraper.call_spider_async` | `await _process_pending_io()` |
| `scrapy/pipelines/media.py:180,200,281-283` | sleeps before cached/normal media results and `call_later(_DEFER_DELAY, wad.callback/errback, ...)` | `_process_pending_io()` plus direct `wad.callback(result)` / `wad.errback(result)` |
| `scrapy/core/downloader/middleware.py:84` | sleep in `download_async` exception path | `_process_pending_io()` |
| `scrapy/core/downloader/__init__.py:222` | sleep in `download_request_async` exception path | `_process_pending_io()` |
| `scrapy/core/spidermw.py:227` | sleep in `scrape_response_async` exception path | `_process_pending_io()` |

## Detection result

Candidate test files are recorded in `detection-draft.json` (single `candidates` array,
repository-relative test paths with the symbols that touch the changed paths and a reason
for each). The strongest candidate is `tests/test_pipeline_media.py`, because it imports
`_defer_sleep_async` directly (line 20), uses it in
`TestMediaPipeline.test_wait_if_request_is_downloading` (line 446), and asserts the media
result caching/waiter behaviour that the change rewrites.
