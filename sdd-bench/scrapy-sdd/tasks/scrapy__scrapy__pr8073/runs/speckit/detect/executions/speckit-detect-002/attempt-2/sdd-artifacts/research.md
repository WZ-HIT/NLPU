# Research: Re-enable DirtyReactorAggregateError Tests

## Decision: Remove only the obsolete skip guards

**Rationale**: The three affected tests contain platform/reactor guards whose sole purpose
is to avoid `DirtyReactorAggregateError` on Windows with asyncio. The PR intends to test
whether those guards are still necessary. Removing only the guards preserves test intent
and minimizes risk.

**Alternatives considered**:

- Replace `pytest.skip` with `xfail`: rejected because the goal is to re-enable the tests,
  not preserve an expected failure.
- Rewrite the tests: rejected because there is no evidence that their assertions or request
  setup are invalid.
- Change downloader product code: rejected because the stated task is test re-enablement.

## Decision: Validate through existing inherited HTTP coverage

**Rationale**: `TestHttpBase` defines the timeout tests inherited by concrete HTTP handler
test classes. Testing the base definitions through the normal matrix avoids duplicate test
logic.

**Alternatives considered**:

- Add copies of the tests to each handler module: rejected as duplication.
- Test only one concrete handler: rejected because the affected definitions are shared.

## Decision: No data model or external contract changes

**Rationale**: This is a test-suite maintenance change with no persisted entities, API
surface, or runtime contract changes.
