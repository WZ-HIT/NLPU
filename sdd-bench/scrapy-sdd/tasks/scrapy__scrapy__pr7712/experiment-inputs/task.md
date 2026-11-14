# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7712`

Base commit: `870803b7fb1ed56c296eb6b51d0212f0460dfdda`

## Title

More granular untyped defs checking in tests.

## Body

List files with problems explicitly, fix problems in files with a small number of them. It should be easier to remove a fully fixed file from the list than to add `-> None` to all its test functions (I would still add type hints to parameters and fixtures though).
