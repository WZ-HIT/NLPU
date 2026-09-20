## 1. Retry Configuration

- [ ] 1.1 Add the pytest rerun dependency/plugin if it is not already available, and configure a small bounded retry count for tests carrying `requires_internet`; verify with a test configuration that the marker selects the retry policy.
- [ ] 1.2 Ensure exhausted retries still report a normal test failure and leave non-Internet tests unretried; verify with targeted pytest collection/config inspection and a deliberate failed rerun in a temporary test.

## 2. Internet-Dependent Tests

- [ ] 2.1 Confirm the retry policy applies to the `TestRealWebsite` classes in `tests/test_downloader_handler_httpx.py`, `tests/test_downloader_handler_twisted_http2.py`, and `tests/test_downloader_handler_twisted_http11.py`; verify by inspecting collected marker metadata without depending on live network availability.
- [ ] 2.2 Run the affected internet-marked tests when network access is available and confirm an intermittent first failure is retried while a persistent failure remains visible.
