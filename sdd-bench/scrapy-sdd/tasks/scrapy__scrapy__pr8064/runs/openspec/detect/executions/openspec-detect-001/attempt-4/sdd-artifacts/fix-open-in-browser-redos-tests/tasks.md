## 1. Re-size the adversarial inputs

- [ ] 1.1 In `tests/test_utils_response.py`, replace the two ~2 MB / ~0.5 MB bodies used by `test_open_in_browser_redos_comment` and `test_open_in_browser_redos_head` with the smallest repetition counts that still spend roughly 0.1-0.5 s inside the historical pattern; verify with a one-off `re` timing script on `rb"<!--.*?-->"` and `rb"(<head(?:>|\s.*?>))"` that each candidate prefix is super-linear between the two chosen sizes
- [ ] 1.2 Keep the recheck-playground provenance comment next to each input and state which historical pattern the input targets; verify by reading the updated comments against the pattern strings passed to the timing check

## 2. Replace the pass/fail criterion

- [ ] 2.1 Change `_assert_open_in_browser_is_fast(body: bytes)` to measure `process_time()` for the adversarial body at size `N` and `2N` (minimum of repeated runs), assert the doubling factor stays below the chosen bound, and keep a coarse seconds-scale ceiling as a hang guard; verify the helper is called by both existing `test_open_in_browser_redos_*` tests without signature changes
- [ ] 2.2 Add the self-validation step inside the helper: run the historical pattern named by the calling test on a short prefix of the advertised input at two sizes and assert super-linear growth, so a non-exploit input fails; verify by temporarily substituting an input that the pattern handles linearly and confirming the assertion fires

## 3. Preserve behavioural coverage

- [ ] 3.1 Confirm `test_open_in_browser`, `test_inject_base_url`, `test_open_in_browser_preserves_html_comments`, `test_open_in_browser_keeps_base_url_of_response`, `test_open_in_browser_injects_base_when_only_in_comment`, `test_open_in_browser_injects_base_before_head_contents`, `test_open_in_browser_text_response_uses_txt_extension`, and `test_open_in_browser_raises_for_unsupported_response_type` are unchanged and still pass, with no edit to `scrapy/utils/response.py`

## 4. Verify the guard

- [ ] 4.1 Run the module, e.g. `python -m pytest tests/test_utils_response.py -q`, and verify the whole file passes, including the two reworked ReDoS tests
- [ ] 4.2 Verify the guard still detects the regression it exists for: temporarily reintroduce a comment/head regex step in `open_in_browser` (or run the helper against the historical pattern on the full-size input), confirm the reworked tests fail, then restore the file
- [ ] 4.3 Run the guard repeatedly (for example 5 consecutive runs of the two `*_redos_*` tests) on a normal and a loaded machine, and verify the outcome does not change with machine speed
