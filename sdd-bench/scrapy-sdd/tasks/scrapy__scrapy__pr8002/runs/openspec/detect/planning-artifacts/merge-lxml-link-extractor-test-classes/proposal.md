## Why

Scrapy now has a single public link extractor implementation, `LxmlLinkExtractor`. Keeping its tests split between a disabled `Base.TestLinkExtractorBase` container and `TestLxmlLinkExtractor` adds indirection without supporting an alternative extractor implementation.

## What Changes

- Merge the reusable `Base.TestLinkExtractorBase` test methods directly into `TestLxmlLinkExtractor`.
- Remove the now-unnecessary `Base` wrapper and inheritance.
- Keep the existing test cases, assertions, fixtures, and `LxmlLinkExtractor` behavior unchanged.

## Capabilities

### New Capabilities

None. This is a test-only refactor with no spec-level behavior change.

### Modified Capabilities

None.

## Impact

Only `tests/test_linkextractors.py` is affected. Production code and public APIs are unchanged.
