## Context

`tests/test_crawl.py::TestCrawl` exercises download delays through the shared
`_test_delay` helper. The helper runs `FollowAllSpider` with a small `total`,
while the mock server generates many links by default and Scrapy deduplicates
repeated requests. The timing assertion can therefore be based on only a few
distinct pages. See `proposal.md` for the motivation; this is a test-only
change and does not alter downloader behavior.

## Goals / Non-Goals

**Goals:**

- Base the download-delay assertion on a larger set of distinct page visits.
- Avoid relying on random link selection to cover enough pages.
- Preserve the no-delay control that demonstrates the test parameters can
  distinguish delayed from undelayed crawls.
- Keep the added test runtime bounded and appropriate for a normal test run.

**Non-Goals:**

- Changing `DOWNLOAD_DELAY`, downloader-slot, scheduler, or deduplication
  behavior in production code.
- Redesigning `FollowAllSpider` or the mock-server resource used by unrelated
  tests.
- Changing the assertion tolerances merely to hide timing variability.

## Decisions

- Increase `total` for the delay tests to provide enough candidate pages for a
  stable average. A single increase is preferred over adding sleeps or a new
  timing mechanism because existing tests and controls already measure real
  crawl timing.
- Prefer a deterministic link order, such as `order="desc"`, for the delay
  helper. This ensures the generated links cover distinct pages instead of
  depending on random sampling to happen to include them. The alternative,
  leaving `order="rand"`, preserves existing style but still permits duplicate
  links and skipped pages.
- Keep the larger page count local to `_test_delay` callers or helper
  parameters so tests that use `FollowAllSpider` for other purposes retain
  their current behavior.
- Keep the zero-delay rerun and its inverse timing assertion. It is the
  guardrail proving that the larger sample did not make the test trivially
  pass.

## Risks / Trade-offs

- Larger crawls increase test runtime. → Use modest delays and only enough
  pages to stabilize the average, then validate the focused tests first.
- Timing tests remain sensitive to loaded CI workers. → Increase the sample
  size and use deterministic, complete link generation rather than weakening
  the tolerance.
- Altering shared spider defaults could affect unrelated tests. → Keep the
  change within `tests/test_crawl.py` unless a narrowly scoped helper change
  proves necessary.

## Migration Plan

No migration is required. This planning change only affects test parameters and
test execution.
