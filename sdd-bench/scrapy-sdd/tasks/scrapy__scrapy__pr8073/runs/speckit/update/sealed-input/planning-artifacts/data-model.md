# Data Model: Re-enable DirtyReactorAggregateError Tests

No data entities are introduced or changed.

The relevant test-level concepts are:

- **Affected test**: A previously skipped test method with an existing behavioral assertion.
- **Skip condition**: The `reactor_pytest == "asyncio"` and `sys.platform == "win32"`
  guard to be removed.
