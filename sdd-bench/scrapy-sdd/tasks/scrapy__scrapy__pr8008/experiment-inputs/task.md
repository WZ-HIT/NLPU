# Pull request task

Repository: `scrapy/scrapy`

Pull request: `8008`

Base commit: `488a762d7173922190ea027e0fb6f6d9d3b59880`

## Title

fix flaky test_slow_pipeline by comparing items unordered

## Body

Fixes #8006

`test_slow_pipeline` asserts a strict item order (A then B), but both
items get an identical artificial delay in `SlowPipeline.process_item`.
Their completion order depends on event-loop scheduling rather than
submission order, so the assertion is racy — reproduced on the Windows
"min" CI job where timer resolution is coarser:
https://github.com/scrapy/scrapy/actions/runs/32053018703/job/95456761821

Fix: added an `ordered` flag to `_test_spider` (default `True`, so every
other test is unaffected). `test_slow_pipeline` now compares items
unordered instead of asserting a strict sequence.

Verified locally with 20x reruns via pytest-repeat, all passing.
