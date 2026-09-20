# Feature Specification: Stabilize Storage Expiry Test

**Feature Branch**: `001-stabilize-storage-expiry-test`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Pull request `scrapy/scrapy#7993`, "Stop test_storage from expiring its cache entry on slow runners"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Keep the pre-expiry assertion reliable (Priority: P1)

As a Scrapy maintainer, I want the cache-storage expiration test to distinguish scheduling delay from actual cache expiration so that slow CI runners do not produce false failures.

**Why this priority**: The existing test performs a successful retrieval immediately after storing a cache entry and before advancing to the expired state. That baseline assertion becomes unreliable when a runner takes longer than the configured expiration window to reach it.

**Independent Test**: Exercise the storage-expiration scenario with an injected delay between storing the entry and performing the first retrieval. The first retrieval must still succeed, and a later retrieval beyond the expiration threshold must still be reported as a miss.

**Acceptance Scenarios**:

1. **Given** a cache entry with a finite expiration interval, **When** the first retrieval happens after an arbitrary scheduling delay but before the test intentionally advances time, **Then** the stored response MUST still be returned.
2. **Given** the successful pre-expiry retrieval, **When** the test advances beyond the expiration threshold, **Then** the next retrieval MUST report a cache miss.
3. **Given** the filesystem, gzip filesystem, DBM, and custom DBM storage variants, **When** the shared storage-expiration test runs, **Then** every variant MUST retain the same pre-expiry and post-expiry assertions.

### Edge Cases

- The runner is descheduled for longer than the configured one-second expiration interval between storing and reading the entry.
- The expiration interval is zero, which means entries never expire and must remain unaffected.
- Time advances at or beyond the expiration boundary after the pre-expiry assertion has completed.
- Filesystem expiration is based on persisted entry age, while DBM expiration is based on a stored timestamp; the test must remain valid for both representations.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The storage-expiration test MUST control the reference time used for the entry's stored timestamp and retrieval checks.
- **FR-002**: The pre-expiry retrieval MUST succeed regardless of real elapsed time on the runner.
- **FR-003**: The expiration phase MUST occur only after the pre-expiry response and its contents have been verified.
- **FR-004**: The post-expiration retrieval MUST continue to verify that the cache reports a miss.
- **FR-005**: Existing filesystem and DBM storage variants MUST continue to exercise the shared behavior without losing coverage.
- **FR-006**: Production cache behavior and public interfaces MUST remain unchanged.

### Key Entities

- **Cache entry**: A stored response associated with a request and a reference time.
- **Controlled reference time**: The test-defined time used for storage and expiration checks.
- **Expiration interval**: The configured duration after which a cache entry is no longer considered valid.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across 100 repeated executions with injected pre-expiry delays, the storage-expiration test reports zero false misses during the pre-expiry assertion.
- **SC-002**: In every execution, the post-expiration assertion still observes a missing cache entry.
- **SC-003**: All existing storage variants retain coverage of the shared expiration scenario.
- **SC-004**: No production source file changes are required to make the test reliable.

## Assumptions

- The pull request is limited to stabilizing an existing test rather than changing cache semantics.
- The shared test remains the appropriate place to cover all storage variants through inheritance.
- A deterministic time-based scenario is preferred over sleeps, retries, or increasing the expiration interval.
