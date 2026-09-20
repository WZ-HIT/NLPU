# Tasks: Exit code 1 on crawler bootstrap errors

- [ ] 1. Add bootstrap-failure handling to `scrapy/commands/fetch.py`.
  _Boundary:_ `scrapy/commands/fetch.py`
  _Depends:_ none

- [ ] 2. Add bootstrap-failure handling to `scrapy/commands/parse.py`.
  _Boundary:_ `scrapy/commands/parse.py`
  _Depends:_ none

- [ ] 3. Fold `bootstrap_failed` into the exit code of `scrapy/commands/check.py`.
  _Boundary:_ `scrapy/commands/check.py`
  _Depends:_ none

- [ ] 4. Add/extend command tests asserting exit code 0 and 1.
  _Boundary:_ `tests/test_command_fetch.py`, `tests/test_command_parse.py`,
  `tests/test_command_check.py`
  _Depends:_ 1, 2, 3
