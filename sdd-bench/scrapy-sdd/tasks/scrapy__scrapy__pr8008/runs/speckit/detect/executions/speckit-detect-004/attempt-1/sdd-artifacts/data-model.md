# Data Model: Stabilize Slow-Pipeline Spider-Start Test

## Test Observation

**Fields**

- `item`: Any value emitted by the spider and delivered by `item_scraped`.
- `response`: Response associated with the scraped item, or `None` where the crawl emits items directly.
- `spider`: Spider instance associated with the observation.

**Rules**

- Observations are appended in actual completion order.
- Observation order is not asserted for the slow-pipeline case.

## Expected Items

**Fields**

- `items`: Ordered collection used by existing tests.
- `ordered`: Comparison mode, defaulting to `True`.

**Rules**

- `ordered=True`: Actual observations must exactly equal the expected sequence.
- `ordered=False`: Actual observations must contain exactly the same items and multiplicities as expected, in any order.
- An empty expected collection means the crawl must scrape no items.

## Crawl Outcome

**Fields**

- `finish_reason`: Must remain `finished`.

**State transitions**

`crawl started -> items emitted through pipelines -> item_scraped observations collected -> crawl finished -> assertions evaluated`
