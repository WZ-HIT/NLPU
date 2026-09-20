# Quickstart: Validate Nested Selector Type Inference

Run these commands only during a later implementation or validation stage; this planning stage does not execute tests.

```bash
python -m pytest tests/test_selector.py -q
```

Expected outcomes:

- Existing response flavor-detection tests pass for HTML, XML, JSON, and text response behavior.
- A selector created from an existing root without an explicit type follows parsel's inferred type.
- Existing JMESPath tests that move between JSON and HTML continue to pass.

Do not treat a successful top-level response type assertion as sufficient; validation must include a selector constructed from an existing root.
