## Why

Nested selectors created from JSON values can be assigned a Scrapy selector type
that conflicts with the value returned by parsel. In particular, selectors
created from non-string JMESPath results can be treated as HTML instead of JSON,
so extracting scalar values can fail.

## What Changes

- Let parsel determine the selector type whenever a selector is constructed
  from a `root` value.
- Keep Scrapy's existing response- and text-based type inference for selectors
  that are not constructed from a nested `root`.
- Preserve explicit selector types and existing behavior for HTML, XML, JSON,
  and text responses.

## Capabilities

### New Capabilities

- `selector`: Determine the type of top-level and nested selectors consistently.

### Modified Capabilities

None.

## Impact

- Affected code: `scrapy/selector/unified.py`.
- Affected tests: `tests/test_selector.py`.
- Dependencies: relies on the installed parsel version to determine the type of
  a supplied root value.
- Public API: no new API; this corrects nested selector behavior.
