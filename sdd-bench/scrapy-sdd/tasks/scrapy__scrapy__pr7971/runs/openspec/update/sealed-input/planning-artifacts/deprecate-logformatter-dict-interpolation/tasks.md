## 1. Compatibility implementation

- [ ] 1.1 Update `logformatter_adapter()` to warn on non-empty dictionary
  `args` and eagerly interpolate them, verified by checking the adapter
  behavior and warning.
- [ ] 1.2 Keep tuple and empty `args` behavior unchanged, verified by adapter
  tests covering tuple and empty values.
- [ ] 1.3 Update `LogFormatter` documentation to recommend tuple arguments and
  describe the dictionary deprecation, verified by documentation review.

## 2. Detection and regression coverage

- [ ] 2.1 Extend `tests/test_utils_log.py` with dictionary deprecation and
  message compatibility coverage.
- [ ] 2.2 Review `tests/test_logformatter.py` for formatter subclasses that
  return dictionary arguments and update or add coverage as needed.
