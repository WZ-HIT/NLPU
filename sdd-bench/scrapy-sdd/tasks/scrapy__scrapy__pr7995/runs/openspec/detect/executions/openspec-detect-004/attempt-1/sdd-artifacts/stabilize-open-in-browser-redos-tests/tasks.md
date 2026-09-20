## 1. Stabilize the regression tests

- [ ] 1.1 Update the CPU-time guard used by `test_open_in_browser_redos_comment` and `test_open_in_browser_redos_head` in `tests/test_utils_response.py`, and verify both tests still fail against the old ReDoS patterns.
- [ ] 1.2 Run the two targeted ReDoS tests under the available interpreter and verify they pass without changing their exploit payloads.
- [ ] 1.3 Run the full `tests/test_utils_response.py` module and verify no other `open_in_browser` regression changes.
