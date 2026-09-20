## 1. Stabilize the ReDoS timing helper

- [ ] 1.1 In `tests/test_utils_response.py`, update
  `_assert_open_in_browser_is_fast` to measure the calling thread's CPU time
  and use a one-second budget.
- [ ] 1.2 Keep the response construction and other setup outside the measured
  region.

## 2. Repair the exploit inputs

- [ ] 2.1 Change the input in `test_open_in_browser_redos_comment` to remove
  the trailing `<!---->` terminator so the body contains no `-->` match.
- [ ] 2.2 Confirm `test_open_in_browser_redos_head` remains unterminated and
  still exercises repeated failed `<head>` searches.

## 3. Verify the focused regression coverage

- [ ] 3.1 Run `pytest tests/test_utils_response.py -k open_in_browser`.
- [ ] 3.2 Confirm comment-preservation and base-tag tests still pass and that
  no runtime or documentation files changed.
