## 1. Stabilize the regression test

- [ ] 1.1 In `tests/test_pipeline_files.py`, change the `last_modified` value
  in `TestFilesPipeline.test_file_path_from_response` from `time.time()` to a
  timestamp one second in the past, and verify the test still has
  `FILES_EXPIRES` set to `0`.
- [ ] 1.2 Confirm the mocked entry is treated as expired even when the host
  clock reports the same tick for consecutive `time.time()` reads.

## 2. Verify the focused behavior

- [ ] 2.1 Run
  `python -m pytest tests/test_pipeline_files.py::TestFilesPipeline::test_file_path_from_response`
  and verify it passes.
- [ ] 2.2 Run the same test repeatedly on Windows CI and verify no
  clock-resolution flake remains.
