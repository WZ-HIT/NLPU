## 1. Helper Change

- [ ] 1.1 Add an `ordered: bool = True` keyword argument to `_test_spider()` in
      `tests/test_spider_start.py` and compare `actual_items` with `expected_items`
      as a multiset when `ordered` is `False` (keeping the current list equality when
      it is `True`); verify by reading the helper and confirming every existing call
      site still compiles with the default argument.

## 2. Test Update

- [ ] 2.1 Pass `ordered=False` from `test_slow_pipeline` while keeping its two expected
      items and the `SlowPipeline` settings unchanged; verify the test still asserts
      that exactly `ITEM_A` and `ITEM_B` are scraped and that `finish_reason` is
      `finished`.

## 3. Verification

- [ ] 3.1 Run `tests/test_spider_start.py` and confirm all cases in the file pass,
      including the single-item tests that rely on the ordered default.
- [ ] 3.2 Re-run `tests/test_spider_start.py::test_slow_pipeline` repeatedly (for
      example 20 times with `pytest-repeat`) and confirm it passes every time, which
      is the evidence that the scheduling-dependent flakiness is gone.
- [ ] 3.3 Run the repository lint/format checks for the modified file (ruff via the
      project's configured pre-commit hooks) and confirm no findings.
