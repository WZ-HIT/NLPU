# Feature Specification: Stabilize Slow-Pipeline Spider-Start Test

**Feature Branch**: `fix-flaky-slow-pipeline`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Pull request 8008 in `scrapy/scrapy`: "fix flaky test_slow_pipeline by comparing items unordered"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trust the slow-pipeline regression test (Priority: P1)

As a Scrapy maintainer, I want `test_slow_pipeline` to verify that both expected items are processed without assuming a completion order that the runtime does not guarantee, so that the same revision produces stable results across operating systems and event-loop implementations.

**Why this priority**: The test currently fails intermittently in CI even when production behavior is correct. That blocks pull requests and hides real regressions.

**Independent Test**: Repeatedly run `test_slow_pipeline` on an environment with coarse timer resolution, then confirm that it passes whenever both expected items are scraped and that it still fails when an item is missing, duplicated, or altered.

**Acceptance Scenarios**:

1. **Given** two items submitted with the same artificial pipeline delay, **When** the test compares scraped items without requiring an order, **Then** either completion order is accepted.
2. **Given** a regression that drops or changes one scraped item, **When** the unordered comparison runs, **Then** the test still fails.
3. **Given** every other spider-start test, **When** the shared helper retains its ordered default, **Then** those tests continue to detect order regressions.

### Edge Cases

- Timer callbacks with equal deadlines may run in either order, or may be coalesced by coarse platform timers.
- The comparison must support the item types already exercised by the helper rather than assuming values are hashable.
- Duplicate scraped items must not be silently accepted as equivalent to a shorter expected sequence.
- Tests with zero or one expected item must retain their existing behavior.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The shared spider-result helper MUST support both order-sensitive and order-insensitive item comparison.
- **FR-002**: Order-sensitive comparison MUST remain the default so existing callers are unaffected.
- **FR-003**: `test_slow_pipeline` MUST use order-insensitive comparison while still requiring the exact expected item multiset.
- **FR-004**: The change MUST NOT alter production crawling, pipeline, signal, or scheduling behavior.
- **FR-005**: The test MUST continue to require a normal `finished` crawl result.
- **FR-006**: The change MUST be limited to test-support code and the affected test.

### Key Entities

- **Scraped item observation**: An item delivered through the `item_scraped` signal during a crawl.
- **Expected item collection**: The exact items a test expects to be delivered, independent of completion order for the slow-pipeline case.
- **Comparison mode**: A per-test choice between order-sensitive and order-insensitive assertion behavior.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Repeated executions of the slow-pipeline test complete without order-related failures on supported CI platforms.
- **SC-002**: A missing, extra, or changed item still causes deterministic failure.
- **SC-003**: All pre-existing ordered spider-start tests retain their current assertions and outcomes.
- **SC-004**: No production module or public API changes are required.

## Assumptions

- The event loop does not guarantee completion order when equally delayed pipeline operations become ready together.
- The PR is a test-stability fix, not a change to Scrapy's documented item-order behavior.
- CI coverage includes platforms where timer resolution makes the original race observable.
