## Why

`scrapy.utils.response.open_in_browser()` is documented to adjust the `base`
tag so that relative links, images and stylesheets resolve against the crawled
page when the response is opened locally. For HTML responses that contain no
`<head>` element, the current implementation silently leaves the body
untouched, so opening such a page shows broken relative URLs
(https://github.com/scrapy/scrapy/issues/6550).

## What Changes

- When an `HtmlResponse` body has no `<head>` element, inject
  `<base href="<response url>">` anyway, adding a `<head>` element in a
  sensible position (immediately after `<html>` when present, otherwise at the
  start of the body) so the injected markup is valid.
- Keep the current guarantees: a base tag that already exists in real markup is
  not duplicated, base tags that only appear inside HTML comments are ignored,
  and comments in the body are preserved as-is.
- Non-HTML responses keep their existing behavior: text responses are written
  as `.txt` files and other response types still raise `TypeError`.
- No public API changes: only the content of the temporary file that is handed
  to the browser changes.

## Capabilities

### New Capabilities

- `open-in-browser`: behavior of `scrapy.utils.response.open_in_browser()` when
  preparing a response body for a local browser, including base-tag injection
  for HTML responses that have no `<head>` element.

### Modified Capabilities

- None. No other capability described in `openspec/specs/` changes.

## Impact

- `scrapy/utils/response.py` (`open_in_browser()`, and the head-detection /
  base-tag insertion logic it relies on).
- `tests/test_utils_response.py`, where the behavior of `open_in_browser()` is
  covered.
- `docs/news.rst` release notes for the fix.
- No new dependencies and no changes to command/shell entry points
  (`scrapy view`, `scrapy shell`) beyond the shared helper.
