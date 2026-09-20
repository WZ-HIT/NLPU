## 1. Callback Execution

- [ ] 1.1 Refactor contract callback wrappers in `scrapy/contracts/__init__.py` to normalize coroutine, async-generator, Deferred, and synchronous results; verify with focused unit tests.
- [ ] 1.2 Ensure pre-process and post-process hooks run in their existing order for asynchronous callbacks; verify hook outcome accounting in `tests/test_contracts.py`.
- [ ] 1.3 Preserve callback error reporting through the contract test result for failures raised during awaiting or async iteration; verify with a failing coroutine test.

## 2. Regression Coverage

- [ ] 2.1 Update async callback contract tests to assert successful `@returns`/`@scrapes` evaluation instead of `TypeError`; verify both coroutine and asynchronous-generator callbacks.
- [ ] 2.2 Add or update an end-to-end `scrapy check` test in `tests/test_command_check.py` for an asynchronous spider callback; verify the command exits successfully.
- [ ] 2.3 Run the focused contract test modules and confirm no synchronous contract regressions.

## 3. Documentation

- [ ] 3.1 Update the contracts documentation if needed to state that coroutine and asynchronous-generator callbacks are supported; verify the rendered narrative matches the implemented behavior.
