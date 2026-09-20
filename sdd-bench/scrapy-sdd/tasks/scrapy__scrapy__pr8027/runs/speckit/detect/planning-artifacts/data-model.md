# Data Model: Download Delay Crawl Coverage

## Delay Crawl Scenario

- **Fields**: total page count, configured delay, randomization flag, maximum simulated latency.
- **Relationships**: Creates a crawler using `FollowAllSpider`.
- **Validation**: Total page count must be greater than one and large enough for a stable average.

## Timing Sample

- **Fields**: ordered response timestamps.
- **Derived value**: average inter-request time = `(last - first) / (count - 1)`.
- **Validation**: At least two timestamps are required; scenarios should use at least three page visits.

## Control Crawl

- **Fields**: same parameters as the delayed scenario, with download delay set to zero.
- **Validation**: Its average must remain below the delayed scenario's meaningful threshold.

## State Transitions

1. Build crawl parameters.
2. Crawl with the configured delay and collect timestamps.
3. Verify the delayed average.
4. Rebuild the scenario with zero delay.
5. Crawl and verify the control average.
