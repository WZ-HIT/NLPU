## 1. Expand the Delay Test Crawls

- [ ] 1.1 Update `TestCrawl._test_delay` and its fixed/randomized callers in `tests/test_crawl.py` to use enough distinct pages for a stable timing average, and verify both focused tests pass with `python -m pytest tests/test_crawl.py -k "fixed_delay or randomized_delay"`.
- [ ] 1.2 Make the delay-test link traversal cover distinct pages deterministically instead of depending on random duplicate links, and verify the focused tests visit the expected number of pages from `FollowAllSpider.times`.
- [ ] 1.3 Retain the zero-delay control assertion in `_test_delay`, and verify the focused tests fail if the control no longer distinguishes delayed from undelayed crawls.

## 2. Regression Verification

- [ ] 2.1 Run `python -m pytest tests/test_crawl.py` and verify all crawl tests pass without changing unrelated behavior.
- [ ] 2.2 If the implementation touches shared test helpers in `tests/spiders.py`, run `python -m pytest tests/test_closespider.py` and verify the other `FollowAllSpider` tests still pass.
