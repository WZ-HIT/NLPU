# Quickstart Validation: Open-in-Browser ReDoS Test Stability

## Prerequisites

- A Scrapy development environment with pytest installed.
- A way to slow or constrain the Python interpreter for the robustness check.
- No production-code changes for this test-stability task.

## Validation Scenarios

### Scenario 1: Normal execution

Run the two targeted regression checks in `tests/test_utils_response.py`:

```bash
pytest tests/test_utils_response.py -k "open_in_browser_redos"
```

Expected outcome: both checks pass without changing the behavior of `open_in_browser`.

### Scenario 2: Slow-interpreter stability

Run the same two checks repeatedly under the chosen CPU constraint or slow interpreter.

Expected outcome: normal linear processing passes consistently and no failure is caused solely by interpreter speed.

### Scenario 3: Regression sensitivity

Compare the revised allowance with a deliberately vulnerable implementation or a controlled simulation.

Expected outcome: catastrophic processing still exceeds the guard and causes a failure, proving that the checks were stabilized rather than disabled.

## References

- Feature contract: [spec.md](./spec.md)
- Implementation plan: [plan.md](./plan.md)
- Detection draft: [detection-draft.json](./detection-draft.json)
