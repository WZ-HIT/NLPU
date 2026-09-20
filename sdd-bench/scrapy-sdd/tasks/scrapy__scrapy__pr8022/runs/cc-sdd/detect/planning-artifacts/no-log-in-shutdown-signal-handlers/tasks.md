# Implementation Plan

- [ ] 1. Defer shutdown logging on the Twisted reactor path
- [ ] 1.1 Change `_signal_shutdown` and `_signal_kill` in `scrapy/crawler.py` to queue `_log_shutdown` / `_log_kill` with `reactor.callFromThread` instead of calling them directly, keeping the existing escalation (`install_shutdown_handlers`) and stop scheduling, and queueing the message before the stop call
  - `reactor.callFromThread(self._log_shutdown, signum)` precedes `reactor.callFromThread(self._graceful_stop_reactor)`; `reactor.callFromThread(self._log_kill, signum)` precedes `reactor.callFromThread(self._stop_reactor)`
  - Neither handler body contains a direct call to `_log_shutdown`, `_log_kill`, or any other logging API
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2, 3.3_
  - _Boundary: scrapy/crawler.py (CrawlerProcessBase signal handlers)_

- [ ] 2. Defer shutdown logging on the reactorless path
- [ ] 2.1 Change `_signal_shutdown_reactorless` to install the kill handler, keep the `self._reactorless_loop is None` early return, and queue `loop.call_soon_threadsafe(self._log_shutdown, signum)` before `loop.call_soon_threadsafe(self._create_shutdown_task)`
  - With no loop, the method still escalates to `_signal_kill_reactorless` and schedules nothing
  - _Requirements: 1.1, 1.2, 1.3, 2.3, 2.5, 3.1_
  - _Boundary: scrapy/crawler.py (AsyncCrawlerProcess signal handlers)_
  - _Depends: 1.1_
- [ ] 2.2 Change `_signal_kill_reactorless` to install `signal.SIG_IGN`, keep the `self._reactorless_loop is None` early return, and queue `loop.call_soon_threadsafe(self._log_kill, signum)` before cancelling `self._reactorless_main_task`
  - The loop is still touched only when it exists; `call_soon_threadsafe` is called for the message even when there is no main task to cancel
  - _Requirements: 1.1, 1.2, 1.3, 2.4, 2.5, 3.2_
  - _Boundary: scrapy/crawler.py (AsyncCrawlerProcess signal handlers)_
  - _Depends: 2.1_

- [ ] 3. Document the constraint at the helper definitions
- [ ] 3.1 Add a comment above `_log_shutdown` / `_log_kill` recording that logging cannot happen inside a signal handler and that these helpers must be invoked from the reactor or event loop thread, leaving the message text unchanged
  - The comment names the failure mode (a write to the same stream while it is being written raises `RuntimeError` and leaves the shutdown unfinished)
  - _Requirements: 1.4, 3.4_
  - _Boundary: scrapy/crawler.py (logging helpers)_

- [ ] 4. Update the reactorless helper unit tests
- [ ] 4.1 In `tests/test_crawler.py::TestAsyncCrawlerProcessReactorlessHelpers`, revise the expectations in `test_signal_kill_reactorless_without_main_task` (and the shutdown counterpart) so `loop.call_soon_threadsafe` is expected for the deferred `_log_kill` / `_log_shutdown` call, while the no-loop tests still assert nothing is scheduled
  - The stubbed loop records `_log_kill` before the cancel call, and `test_signal_kill_reactorless_without_loop` still schedules nothing
  - Add a case asserting `_signal_shutdown_reactorless` queues `_log_shutdown` before `_create_shutdown_task`
  - _Requirements: 2.3, 2.4, 2.5, 3.3_
  - _Boundary: tests/test_crawler.py_
  - _Depends: 2.1, 2.2_

- [ ] 5. Confirm the subprocess shutdown tests still observe the messages
- [ ] 5.1 Re-run the graceful and forced shutdown cases in `tests/test_crawler_subprocess.py` for `TestCrawlerProcessSubprocess` and `TestAsyncCrawlerProcessSubprocess` and adjust them only if the deferred emission changes the observed stderr ordering
  - "shutting down gracefully" and "forcing unclean shutdown" are still observed on stderr for both paths
  - _Requirements: 3.1, 3.2, 3.3_
  - _Boundary: tests/test_crawler_subprocess.py_
  - _Depends: 1.1, 2.2_
