# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7763`

Base commit: `1157b3e235c957f89e5d598ad2cc2db7779dae9c`

## Title

Support iterable values in BaseSettings.update()

## Body

This makes `BaseSettings.update()` accept iterable key value pairs while keeping the existing behavior for mappings, JSON strings, and `BaseSettings` values.

Resolves #7759.
