# Feature Specification: Download Delay Crawl Coverage

**Feature Branch**: `detect`

**Created**: 2026-09-19

**Status**: Draft

**Input**: Pull request 8027: "Crawl more pages in the download delay tests instead of skipping them"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Exercise fixed download delays with enough crawl work (Priority: P1)

As a Scrapy maintainer, I want the fixed-delay crawl test to visit enough pages to measure the configured delay reliably, so that it provides a meaningful signal without being skipped.

**Why this priority**: Fixed-delay behavior is the baseline for downloader throttling.

**Independent Test**: Run the fixed-delay test and verify that measured inter-request timing exceeds the configured delay and that a no-delay control does not show the same timing.

**Acceptance Scenarios**:

1. **Given** a crawl using a fixed `DOWNLOAD_DELAY`, **When** several pages are visited, **Then** the average inter-request time reflects the configured delay.
2. **Given** the same parameters without a delay, **When** the control crawl runs, **Then** its average inter-request time is below the meaningful-delay threshold.

---

### User Story 2 - Exercise randomized download delays with enough crawl work (Priority: P2)

As a Scrapy maintainer, I want the randomized-delay crawl test to visit enough pages to distinguish the randomized delay from an unthrottled crawl without skipping.

**Why this priority**: Randomized delay is a supported variant of the same downloader behavior.

**Independent Test**: Run the randomized-delay test and verify the delayed-versus-control timing relationship with the randomized tolerance.

**Acceptance Scenarios**:

1. **Given** a crawl using `RANDOMIZE_DOWNLOAD_DELAY`, **When** several pages are visited, **Then** the average inter-request time reflects the randomized delay range.
2. **Given** the same parameters without a delay, **When** the control crawl runs, **Then** the test parameters remain meaningful.

### Edge Cases

- Random link selection may revisit pages; enough distinct pages must still be visited for timing.
- The randomized-delay tolerance must remain wider than the fixed-delay tolerance.
- Slow or fast hosts must not turn a meaningful timing failure into a skipped test.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Fixed and randomized delay crawl tests MUST crawl more than one content page.
- **FR-002**: Delay tests MUST assert that observed inter-request timing exceeds the configured delay.
- **FR-003**: Delay tests MUST retain a no-delay control assertion.
- **FR-004**: The randomized-delay test MUST retain a wider tolerance than the fixed-delay test.
- **FR-005**: The change MUST remain confined to tests and test support code.
- **FR-006**: Tests MUST not skip solely because the original page count was too small.

### Key Entities

- **Delay crawl scenario**: A mocked crawl configured with fixed or randomized delay.
- **Timing sample**: Per-page response timestamps used to calculate average inter-request time.
- **Control crawl**: The same scenario with `DOWNLOAD_DELAY` set to zero.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Both delay scenarios visit at least three pages per crawl.
- **SC-002**: Both delayed crawls and both controls produce non-empty timing samples.
- **SC-003**: Both delayed averages exceed their configured thresholds.
- **SC-004**: Both control averages remain below the meaningful-delay threshold.
- **SC-005**: No production source file changes are required.

## Assumptions

- The mock server remains the source of crawl pages.
- Existing tolerance values remain appropriate after increasing page count.
