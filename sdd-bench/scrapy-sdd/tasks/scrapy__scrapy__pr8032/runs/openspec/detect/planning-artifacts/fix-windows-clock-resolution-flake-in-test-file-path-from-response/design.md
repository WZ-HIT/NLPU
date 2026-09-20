## Context

See `proposal.md` - Why. `FilesPipeline._onsuccess()` treats a cached file as
expired when its age in days is greater than `FILES_EXPIRES`. The test sets
`FILES_EXPIRES` to `0` and mocks `last_modified` with `time.time()`. On a clock
whose resolution is coarser than the elapsed test setup time, both reads can
report the same value, producing an age of zero and an unexpected `uptodate`
result.

## Goals / Non-Goals

**Goals:**

- Make the mocked timestamp reliably older than the later freshness check.
- Keep the test focused on selecting the response-derived path when the
  response-less path has an expired cached entry.

**Non-Goals:**

- Changing expiration semantics or production code.
- Changing unrelated file-pipeline tests.

## Decisions

Use a timestamp one second in the past, such as `time.time() - 1`, instead of
`time.time()`. With `FILES_EXPIRES=0`, any positive age is sufficient, and one
second exceeds typical Windows clock-update intervals. A fixed epoch timestamp
would also work but would obscure the test's intent to represent a cached file
that is just expired.

## Risks / Trade-offs

- The cache entry is intentionally stale rather than nominally fresh. → This is
  aligned with the test comment and avoids dependence on host clock precision.
- The test still depends on wall-clock advancement, but the one-second margin
  is much larger than the Windows clock-update interval. → Keep the targeted
  assertion as the regression check.
