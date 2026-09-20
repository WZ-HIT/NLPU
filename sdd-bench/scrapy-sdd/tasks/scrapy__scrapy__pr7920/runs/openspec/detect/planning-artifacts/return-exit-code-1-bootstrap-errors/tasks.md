# Tasks

## 1. Exit-code behavior

- [ ] 1.1 In `scrapy/commands/check.py`, set `exitcode` to `1` after the
  crawler process finishes when `bootstrap_failed` is true.
- [ ] 1.2 In `scrapy/commands/parse.py`, apply the same bootstrap-failure
  exit-code handling.
- [ ] 1.3 In `scrapy/commands/fetch.py`, apply the same bootstrap-failure
  exit-code handling.

## 2. Regression coverage

- [ ] 2.1 Add a command-level test in `tests/test_command_check.py` that
  triggers a bootstrap failure and asserts exit code `1`.
- [ ] 2.2 Add the corresponding bootstrap-failure exit-code test in
  `tests/test_command_parse.py`.
- [ ] 2.3 Add the corresponding bootstrap-failure exit-code test in
  `tests/test_command_fetch.py`.

## 3. Verification

- [ ] 3.1 Run the three affected command test modules.
- [ ] 3.2 Confirm existing success and usage-error exit-code tests still pass.
