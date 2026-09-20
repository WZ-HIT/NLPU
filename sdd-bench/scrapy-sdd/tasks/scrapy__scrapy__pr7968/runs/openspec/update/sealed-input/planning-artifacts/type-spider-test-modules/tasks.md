## 1. Type Spider Test Helpers

- [ ] 1.1 Add annotations to `tests/spiders.py` and verify with the focused mypy test environment.
- [ ] 1.2 Add annotations to `tests/utils/bases/spider.py` and verify with the focused mypy test environment.

## 2. Type Spider Behavior Tests

- [ ] 2.1 Add annotations to `tests/test_spider.py` and verify with the focused mypy test environment.
- [ ] 2.2 Add annotations to `tests/test_spider_crawl.py` and verify with the focused mypy test environment.
- [ ] 2.3 Add annotations to `tests/test_spider_sitemap.py` and verify with the focused mypy test environment.

## 3. Type Spider Middleware Tests

- [ ] 3.1 Add annotations to `tests/test_spidermiddleware_output_chain.py` and verify with the focused mypy test environment.
- [ ] 3.2 Add annotations to `tests/test_spidermiddleware_process_start.py` and verify with the focused mypy test environment.

## 4. Remove Temporary Exemptions

- [ ] 4.1 Remove the seven typed spider-related modules from the `check_untyped_defs = false` override in `pyproject.toml`.
- [ ] 4.2 Run the mypy test environment for the affected modules and confirm no new errors.
