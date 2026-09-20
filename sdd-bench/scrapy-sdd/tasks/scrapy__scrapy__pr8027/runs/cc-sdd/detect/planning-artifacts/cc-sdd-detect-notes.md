# cc-sdd detect phase notes (planning only)

Scope: planning-only. No project code or tests were modified, no tests were run,
no dependencies were installed. Both cc-sdd planning artifacts live in this
mounted planning directory (`/workspace/.kiro/specs`).

## Inputs

- Task: `/task-input/task.md` — repository `scrapy/scrapy`, PR `8027`,
  base commit `da7c2fc59e286e796d0f8cfe01d4363d6fa3729f`, title
  "Crawl more pages in the download delay tests instead of skipping them".
- Snapshot: `/workspace` at the base commit (single squashed commit, so no PR diff
  is available locally; candidates were derived from the code that the PR title
  points at).

## Spec

Goal: produce a detection draft listing candidate test locations that the PR is
expected to touch, so a later stage can run and verify them.

Observations that drive the candidate set:

- `tests/test_downloaderslotssettings.py::test_delay` checks
  `abs((second - first) - slots[slot].delay) < tolerance` for each slot, but
  `DownloaderSlotsSettingsTestSpider` issues only two requests per slot
  (`parse` -> `not_parse`, `not_parse` yields nothing), so no further pages are
  crawled per slot.
- `tests/test_crawl.py::TestCrawl::_test_delay` (used by `test_fixed_delay` and
  `test_randomized_delay`) crawls `FollowAllSpider` with `total=3` pages and adds
  a second `DOWNLOAD_DELAY=0` control crawl, whose comment states the `total` /
  `delay` combination may otherwise be too small for the average-delay
  assertion to mean anything — i.e. the crawl intentionally stays short.
- `tests/spiders.py::FollowAllSpider` (`total`, `show`, `order`, `maxlatency`)
  decides how many pages those delay crawls reach.
- `tests/mockserver/http_resources.py::Follow` generates the linked pages those
  crawls visit (`total`, `show`, `order`, `maxlatency`); `Delay` serves the
  delayed responses reused by latency tests.

Deliverable: `detection-draft.json` in this directory, a single `candidates`
array whose entries are repository-relative test paths with `symbols` and
`reason`.

## Detect result

Ranked candidates (most likely to be touched by the PR first):

1. `tests/test_downloaderslotssettings.py`
2. `tests/test_crawl.py`
3. `tests/spiders.py`
4. `tests/mockserver/http_resources.py`

Excluded on purpose: `tests/benchmarks/test_crawl.py::test_overhead_delay` (a
CodSpeed benchmark of crawl overhead, not a download-delay behavior test),
`tests/test_closespider.py` (uses `FollowAllSpider` but asserts close behavior),
and `tests/test_extension_throttle.py` (asserts `Slot.delay` values in
isolation, without crawling pages).
