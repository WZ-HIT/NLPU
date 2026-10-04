# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7643`

Base commit: `6393858c7e45ed5393fe98b570505f04855664c1`

## Title

Refactor and improve catching warnings in tests.

## Body

Should help with #7262 (some resource warnings remain)

This mostly replaces `catch_warnings(record=True)` + manual examination of caught warnings (either with `pytest.warns()` or with some warning filter). 

One note: I've tried using the `with warnings.catch_warnings(action="error")` form but it [requires Python 3.11](https://docs.python.org/3/library/warnings.html#warnings.catch_warnings).
