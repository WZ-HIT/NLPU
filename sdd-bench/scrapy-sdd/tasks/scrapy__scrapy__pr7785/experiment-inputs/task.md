# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7785`

Base commit: `e710b9c18e18f0a3fe104fbfc72d49c221dfe448`

## Title

Add type hints to test_link.py and test_downloadermiddleware_stats.py

## Body

Adds full type annotations to two small, previously-untyped test
modules and removes them from the mypy allow_untyped_defs override
list in pyproject.toml.

CONTRIBUTING.md mentions: "If you enjoy code cleanup, we welcome
fixes for issues detected by our static analysis tools. See
pyproject.toml for silenced issues that may need addressing."

Verified locally with:
- pytest tests/test_link.py tests/test_downloadermiddleware_stats.py
- mypy tests/test_link.py tests/test_downloadermiddleware_stats.py
- ruff check / ruff format --check

No behavior changes, only type annotations and one `# type: ignore`
comment for an intentional invalid-type test case.
