# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7545`

Base commit: `4a165508591da164393c448eebc86c9aa48081da`

## Title

Convert tests that fail with testfixtures 12.0.0

## Body

* `TestTopLevelFormatter`: `LogCapture` no longer inherits from `logging.Handler` so this breaks
* `TestHttpErrorMiddlewareIntegrational`: for some reason the second usage of `LogCapture` fails asserts, but only on macOS
