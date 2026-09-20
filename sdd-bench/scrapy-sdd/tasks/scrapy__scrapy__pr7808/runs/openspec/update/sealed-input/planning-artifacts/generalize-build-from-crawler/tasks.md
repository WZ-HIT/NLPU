## 1. Crawler-level construction

- [ ] 1.1 Build `LOG_FORMATTER` with `build_from_crawler()` in `Crawler._apply_settings()` and verify `tests/test_logformatter.py` passes
- [ ] 1.2 Build the extension manager with `build_from_crawler()` in `Crawler._apply_settings()` and verify `tests/test_crawler.py` passes
- [ ] 1.3 Build `STATS_CLASS` with `build_from_crawler()` and verify `tests/test_stats.py` passes

## 2. Engine-level construction

- [ ] 2.1 Build `DownloaderMiddlewareManager` with `build_from_crawler()` in `ScrapyDownloader.__init__()` and verify `tests/test_core_downloader.py` passes
- [ ] 2.2 Build `SpiderMiddlewareManager` and `ITEM_PROCESSOR` with `build_from_crawler()` in `Scraper.__init__()` and verify `tests/test_core_scraper.py` passes
- [ ] 2.3 Build the `DOWNLOADER` class with `build_from_crawler()` in `ExecutionEngine.__init__()` and verify `tests/test_engine.py` passes

## 3. Extension and middleware construction

- [ ] 3.1 Build `MailSender` with `build_from_crawler()` in `MemoryUsage` and `StatsMailer` and verify `tests/test_extension_memusage.py` and `tests/test_extension_statsmailer.py` pass
- [ ] 3.2 Build `ROBOTSTXT_PARSER` with `build_from_crawler()` in `RobotsTxtMiddleware` and verify `tests/test_downloadermiddleware_robotstxt.py` passes

## 4. Coverage and docs

- [ ] 4.1 Add tests that configured components without `from_crawler()` are accepted, and verify `tests/test_utils_misc/__init__.py` still passes
- [ ] 4.2 Update `docs/topics/components.rst` to state that `from_crawler()` is optional, and verify the docs build
- [ ] 4.3 Add a release-note entry under the unreleased section of `docs/news.rst`
