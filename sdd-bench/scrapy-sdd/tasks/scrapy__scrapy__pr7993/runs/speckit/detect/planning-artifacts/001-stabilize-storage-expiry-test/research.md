# Phase 0 Research: Stabilize Storage Expiry Test

## Decision: Control the test clock instead of relying on real elapsed time

**Rationale**: Both cache-storage implementations check the current time against a persisted timestamp when deciding whether an entry has expired. Patching the storage module's time function gives the test a deterministic pre-expiry state and a deterministic post-expiry state. The successful retrieval can happen at any real time without crossing the intended expiration boundary.

**Alternatives considered**:

- Increase the one-second expiration interval. Rejected because a sufficiently slow or suspended runner can still exceed any finite wall-clock window.
- Retry the first retrieval. Rejected because retries hide the timing ambiguity and do not make the assertion deterministic.
- Add a sleep or synchronization barrier. Rejected because it adds runtime without controlling the expiration decision.
- Change production code to separate storage time from expiration time. Rejected because the defect is in the test scenario and the PR scope is test-only.

## Decision: Advance time only after pre-expiry verification

**Rationale**: The test's first phase must establish that a stored response is readable before expiry. Its second phase must establish that the same entry becomes unreadable after expiry. Keeping those phases explicit preserves both contract checks and makes any future regression obvious.

**Alternatives considered**:

- Remove the pre-expiry retrieval. Rejected because it would weaken coverage and could allow store/retrieve regressions to pass.
- Combine both retrievals under one patched time value. Rejected because the test must cross the expiration boundary to verify the miss.

## Decision: Keep the scenario in the shared storage mixin

**Rationale**: `StorageTestMixin.test_storage` is inherited by filesystem, gzip filesystem, DBM, and custom DBM test classes. Improving the shared method keeps behavior consistent across all supported storage variants without duplicating code.

**Alternatives considered**:

- Override the test for each concrete storage class. Rejected because it duplicates the same timing fix and risks variant drift.

## Implementation Constraint Discovered

The filesystem storage implementation evaluates expiration against the cached metadata file's modification time, while DBM storage compares against a timestamp stored at write time. The eventual deterministic sequence must therefore remain valid for both persisted age representations. The test should patch the module time consistently and choose its controlled values so the first lookup is fresh and the second lookup is expired for both implementations.
