## Why

Scrapy 2.18 changed `LogFormatter` results to use lazy logging. Custom formatters
that return a dictionary in `args` could rely on the previous eager
`msg % args` interpolation, so the change can break existing formatters.

## What Changes

- Deprecate returning a dictionary as `LogFormatter` `args`.
- Continue interpolating dictionary arguments eagerly for backward
  compatibility, while emitting `ScrapyDeprecationWarning`.
- Keep tuple arguments on the lazy logging path.
- Document that custom formatters should return tuple arguments.

## Capabilities

### New Capabilities

- `log-formatting`: Defines compatibility and deprecation behavior for values
  returned by `LogFormatter` methods and adapted by `logformatter_adapter`.

### Modified Capabilities

- None.

## Impact

Affected code is `scrapy/utils/log.py`; documentation and tests are affected.
Existing dictionary-based formatters keep working during the deprecation
period, while tuple-based formatters retain lazy logging.
