## 1. Replace the delay helper

- [ ] 1.1 In `scrapy/utils/defer.py`, replace `_defer_sleep_async()` (which awaited `sleep(_DEFER_DELAY)`) with a helper that yields to the event loop twice via `sleep(0)`, with a docstring stating the ordering guarantee; verify with `python -c "import scrapy.utils.defer"` and by grepping that no call site still uses the old name.
- [ ] 1.2 Keep `_DEFER_DELAY` and the deprecated `defer_fail()`, `defer_succeed()`, and `defer_result()` helpers unchanged; verify that `scrapy/utils/defer.py` still references `_DEFER_DELAY` for them.

## 2. Update call sites

- [ ] 2.1 Point `scrapy/core/scraper.py` (callback dispatch) and `scrapy/core/spidermw.py` (spider middleware exception path) at the new helper; verify by reading the imports and the call sites.
- [ ] 2.2 Point `scrapy/core/downloader/middleware.py` and `scrapy/core/downloader/__init__.py` (downloader exception and slot paths) at the new helper; verify by reading the imports and the call sites.
- [ ] 2.3 In `scrapy/pipelines/media.py`, use the new helper for the cached-result and pre-download yields, add the yield before caching the finished result, and resolve waiting deferreds directly instead of through `call_later(_DEFER_DELAY, ...)`; drop the now unused `_DEFER_DELAY`/`call_later` imports; verify with `rg "_defer_sleep_async|_DEFER_DELAY" scrapy/`.

## 3. Update tests

- [ ] 3.1 Update `tests/test_pipeline_media.py` to import the renamed helper and adjust `test_wait_if_request_is_downloading` so it still keeps the first request downloading; verify with `pytest tests/test_pipeline_media.py`.
- [ ] 3.2 Review tests that exercise callback dispatch and media results for reliance on the removed delay (`tests/test_engine.py`, `tests/test_core_scraper.py`, `tests/test_utils_defer.py`, `tests/test_downloadermiddleware.py`, `tests/test_spidermiddleware.py`, `tests/test_pipeline_files.py`, `tests/test_pipeline_images.py`) and update any that assert the old timing; verify with the corresponding `pytest` runs.
- [ ] 3.3 Confirm no test or helper still references the removed private symbol with `rg "_defer_sleep_async" tests/ conftest.py`.

## 4. Verify behavior and document

- [ ] 4.1 Run the engine, scraper, middleware, and pipeline test modules end to end and confirm they pass on both the default and asyncio reactors where applicable.
- [ ] 4.2 Check that a short crawl no longer spends ~100 ms per callback by comparing crawl duration before and after the change (e.g. `pytest tests/test_engine.py --durations=10`).
- [ ] 4.3 Add a release note under the appropriate heading in `docs/news.rst` describing the removed per-callback and per-media-result delay.
