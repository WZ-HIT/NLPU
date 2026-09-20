## 1. Remove the exemption

- [ ] 1.1 Remove the 14-module `check_untyped_defs = false` override and TODO
  block from `pyproject.toml`, then verify the surrounding mypy configuration
  still parses.
- [ ] 1.2 Run the repository mypy check and record the newly reported errors;
  verify every reported file is one of the affected test modules or a helper it
  owns.

## 2. Type the affected tests

- [ ] 2.1 Annotate command-line test helpers and tests in
  `tests/test_cmdline/__init__.py`; verify that file type-checks.
- [ ] 2.2 Annotate the downloader-slot, dupe-filter, extension, link-extractor,
  and log-formatter test modules; verify each file type-checks.
- [ ] 2.3 Annotate the mail, priority-queue, scheduler-base, settings, squeue,
  and stats test modules; verify each file type-checks.
- [ ] 2.4 Run the full mypy check and verify it reports no errors.

## 3. Verify behavior

- [ ] 3.1 Run the affected test modules with pytest and verify they pass.
- [ ] 3.2 Run the standard test suite or the project's normal CI-equivalent
  test command and verify there are no regressions.
