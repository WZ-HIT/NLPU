# Phase 0 Research: Open-in-Browser ReDoS Test Stability

## Decision: Limit the change to the test module

**Rationale**: PR 7995 is titled as a test-stability fix. The production implementation already uses a linear comment remover and a bounded head-search regular expression. Changing production code would exceed the stated scope without evidence of a product defect.

**Alternatives considered**:

- Change the production regular expressions again: rejected because no production failure is described.
- Remove the timing checks: rejected because it would eliminate the ReDoS regression signal.
- Mark the checks as expected failures: rejected because failures on slow interpreters are environment-dependent and xfail would also mask genuine regressions.

## Decision: Keep both pathological inputs and their regression intent

**Rationale**: The comment and head inputs exercise different former failure modes. Both must remain present so the PR fixes flakiness without silently reducing security coverage.

**Alternatives considered**:

- Keep only one ReDoS check: rejected because it would remove coverage for the other historical pattern.
- Reduce input sizes substantially: rejected as a default because it may move execution below the detection threshold for a vulnerable implementation.

## Decision: Use an environment-tolerant but bounded performance signal

**Rationale**: The current checks use CPU process time with a 20 ms maximum. That duration is small enough that normal interpreter variation can cause false failures while catastrophic behavior is expected to be orders of magnitude larger. A revised allowance should be calibrated to distinguish linear processing from catastrophic processing on slow interpreters.

**Alternatives considered**:

- Switch to wall-clock time: rejected because it is more exposed to scheduler noise.
- Remove the upper bound and assert only output correctness: rejected because it would no longer detect a performance regression.
- Use an unbounded benchmark: rejected because unit-test runtime must remain bounded.

## Open Questions

None. The implementation phase can calibrate the final allowance from a slow interpreter while retaining a deliberately vulnerable comparison.
