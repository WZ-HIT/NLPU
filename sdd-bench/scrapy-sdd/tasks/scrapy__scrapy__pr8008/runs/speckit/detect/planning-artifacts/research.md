# Research: Stabilize Slow-Pipeline Spider-Start Test

## Decision: Preserve ordered comparison as the helper default

**Rationale**: Only `test_slow_pipeline` relies on completion order while assigning equal delays to both items. Existing tests should continue to catch accidental reordering.

**Alternatives considered**:

- Make the entire helper order-insensitive. Rejected because it weakens unrelated regression coverage.
- Change the pipeline delay to force a deterministic order. Rejected because it tests scheduling timing rather than the intended slow-pipeline behavior and may remain platform-sensitive.

## Decision: Compare unordered results as a lossless multiset

**Rationale**: The assertion must accept either completion order while still detecting missing, extra, changed, or duplicated items. The comparison should not require expected items to be hashable because the helper accepts arbitrary item values.

**Alternatives considered**:

- Compare lengths only. Rejected because changed items would pass.
- Convert directly to a set. Rejected because dictionary items are not hashable.
- Add a production ordering guarantee. Rejected because the PR is explicitly test-only and the existing behavior is valid.

## Decision: Limit scope to `tests/test_spider_start.py`

**Rationale**: The race, shared helper, and only caller that needs unordered semantics are all in this module. No production behavior or public contract changes are needed.

**Alternatives considered**:

- Rewrite pipeline scheduling. Rejected as unnecessary and high risk.
- Duplicate a special assertion into the test. Rejected because the shared helper can express both comparison modes cleanly.
