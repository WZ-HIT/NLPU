# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7377`

Base commit: `58d85282cf785369bd9f2eddcce0889f60d8a065`

## Title

improve handling of timedeltas

## Body

- fix negative elapsed times when system clock changes
- reduce flaky timeout behavior caused by clock adjustments
- improve download latency accuracy
- make delay scheduling more stable
