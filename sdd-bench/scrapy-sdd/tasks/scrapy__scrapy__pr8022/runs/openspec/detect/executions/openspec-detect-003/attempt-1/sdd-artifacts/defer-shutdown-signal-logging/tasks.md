## 1. Change the shutdown handlers

- [ ] 1.1 In `scrapy/crawler.py`, replace the inline `self._log_shutdown(signum)` in `CrawlerProcess._signal_shutdown` with `reactor.callFromThread(self._log_shutdown, signum)`, keeping it before the `callFromThread(self._graceful_stop_reactor)` call, and verify by reading the function that no logging call remains inside the handler body
- [ ] 1.2 In `scrapy/crawler.py`, replace the inline `self._log_kill(signum)` in `CrawlerProcess._signal_kill` with `reactor.callFromThread(self._log_kill, signum)`, keeping it before the `callFromThread(self._stop_reactor)` call
- [ ] 1.3 In `scrapy/crawler.py`, move the `_log_shutdown` call in `AsyncCrawlerProcess._signal_shutdown_reactorless` to `loop.call_soon_threadsafe(self._log_shutdown, signum)` after the `self._reactorless_loop is None` early return, keeping it before `call_soon_threadsafe(self._create_shutdown_task)`; verify the handler still installs `self._signal_kill_reactorless` first
- [ ] 1.4 In `scrapy/crawler.py`, move the `_log_kill` call in `AsyncCrawlerProcess._signal_kill_reactorless` to `loop.call_soon_threadsafe(self._log_kill, signum)` after the `self._reactorless_loop is None` early return, keeping it before the main-task cancel scheduling; verify the handler still installs `signal.SIG_IGN` first
- [ ] 1.5 Add a short comment above `_log_shutdown` / `_log_kill` documenting that they must be called from the reactor or event loop thread and why logging is not safe inside a signal handler

## 2. Update the affected tests

- [ ] 2.1 In `tests/test_crawler.py`, update `TestAsyncCrawlerProcessReactorlessHelpers.test_signal_kill_reactorless_without_main_task` so it asserts the kill notice is scheduled on the loop (and that the main task is not cancelled) instead of asserting that nothing is scheduled, and verify it passes with `pytest tests/test_crawler.py::TestAsyncCrawlerProcessReactorlessHelpers`
- [ ] 2.2 Add unit coverage in `tests/test_crawler.py` for the reactorless handlers scheduling the shutdown/kill notice when a loop is present, and verify the new tests fail against the previous inline-logging implementation and pass after the change
- [ ] 2.3 Confirm the subprocess shutdown tests still observe the notices in the expected order (`tests/test_crawler_subprocess.py::TestCrawlerProcessSubprocess::test_shutdown_graceful`, `::test_shutdown_forced` and the `TestAsyncCrawlerProcessSubprocess` counterparts); extend them only if the notices are no longer observable, and verify with `pytest tests/test_crawler_subprocess.py -k shutdown`

## 3. Verification

- [ ] 3.1 Run `pytest tests/test_crawler.py tests/test_crawler_subprocess.py -k "signal or shutdown"` and verify no failure
- [ ] 3.2 Run the broader `pytest tests/test_crawler.py tests/test_crawler_subprocess.py tests/test_utils_ossignal.py` and verify no regression in the signal/shutdown paths
