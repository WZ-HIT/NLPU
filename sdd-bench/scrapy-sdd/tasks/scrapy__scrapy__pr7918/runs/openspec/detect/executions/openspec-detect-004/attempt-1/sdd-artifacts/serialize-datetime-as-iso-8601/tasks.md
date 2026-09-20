## 1. Implement ISO 8601 JSON encoding

- [ ] 1.1 Update temporal value handling in `scrapy/utils/serialize.py` to use ISO 8601 representations, and verify focused encoder tests cover date, time, naive datetime, aware datetime, and microseconds.

## 2. Align regression coverage

- [ ] 2.1 Update the direct encoder expectations in `tests/test_utils_serialize.py` for the ISO 8601 `T` separator and verify the focused encoder tests pass.
- [ ] 2.2 Update the JSON exporter datetime expectation in `tests/test_exporters.py` for the ISO 8601 representation and verify the focused JSON/JSON Lines exporter tests pass.

## 3. Validate integration

- [ ] 3.1 Verify JSON feed output containing datetime values uses ISO 8601 without changing CSV or XML exporter behavior.
