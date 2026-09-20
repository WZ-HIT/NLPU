## 1. Selector Type Handling

- [ ] 1.1 Update `Selector.__init__` so Scrapy's HTML/XML/JSON inference runs only when no nested `root` is supplied, and verify the condition by reviewing direct response, text, and root construction paths.
- [ ] 1.2 Add regression coverage in `tests/test_selector.py` for a nested selector created from a non-string JSON scalar, verifying the selector type is `"json"` and `get()` returns the scalar.
- [ ] 1.3 Run the focused selector tests with `pytest tests/test_selector.py` and verify they pass.
- [ ] 1.4 Run the affected response-selector tests with `pytest tests/test_http_response_text.py` and verify existing top-level type inference remains unchanged.
