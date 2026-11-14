# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7736`

Base commit: `b3670369b8620ae645a08bb27f553ec6bf830573`

## Title

Test restructuring

## Body

Random file splits/moving helpers out of test files to reduce `from test_foo import` imports. We could do much more but that needs more thinking about e.g. test_engine, test_crawl and test_crawler which are mixed bags of e2e and unit tests of various parts.

No code or behavior changes. 
