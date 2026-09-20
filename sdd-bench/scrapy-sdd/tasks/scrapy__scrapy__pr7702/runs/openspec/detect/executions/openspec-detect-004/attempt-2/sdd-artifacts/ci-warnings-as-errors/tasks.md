## 1. Enable and inventory

- [ ] 1.1 Configure pytest to treat warnings as errors in the shared test configuration.
- [ ] 1.2 Run the current test matrix without changing test expectations and group warning failures by category, message, and originating module.
- [ ] 1.3 Classify each failure as Scrapy-owned, intentionally deprecated behavior, or third-party/interpreter noise.

## 2. Resolve warning failures

- [ ] 2.1 Fix unintended warnings emitted by Scrapy code paths.
- [ ] 2.2 Update tests for intentional deprecations to use `pytest.warns()` or tightly scoped warning capture with assertions.
- [ ] 2.3 Add narrowly scoped, documented filters for third-party or interpreter warnings that cannot be fixed in this repository.
- [ ] 2.4 Remove or narrow obsolete warning suppressions that are no longer needed.

## 3. Validate the policy

- [ ] 3.1 Re-run the affected tests locally under the new warning policy.
- [ ] 3.2 Run the full CI test matrix, including minimum/extra dependency and reactor variants.
- [ ] 3.3 Confirm every remaining warning filter has a specific rationale and does not hide Scrapy-owned warnings.
