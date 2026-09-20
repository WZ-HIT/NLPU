## Why

Spider-related test modules remain exempted from mypy's untyped-definition checks in `pyproject.toml`. Removing that exemption after adding the missing annotations closes a typing gap in the test suite.

## What Changes

- Type the spider helpers, spider behavior tests, sitemap tests, spider middleware tests, and shared spider test base that are currently listed under the `check_untyped_defs = false` test override.
- Remove those spider-related modules from the temporary mypy exemption list once they pass strict checking.
- Do not change production behavior, public APIs, or test semantics.

## Capabilities

### New Capabilities

None. This is a test-only typing refactor with no observable product behavior change.

### Modified Capabilities

None.

## Impact

- `tests/spiders.py`
- `tests/test_spider.py`
- `tests/test_spider_crawl.py`
- `tests/test_spidermiddleware_output_chain.py`
- `tests/test_spidermiddleware_process_start.py`
- `tests/test_spider_sitemap.py`
- `tests/utils/bases/spider.py`
- `pyproject.toml` mypy override list
