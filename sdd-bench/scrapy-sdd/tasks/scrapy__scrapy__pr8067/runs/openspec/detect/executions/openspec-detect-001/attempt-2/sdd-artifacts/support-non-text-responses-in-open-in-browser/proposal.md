## Why

`open_in_browser()` currently rejects every response that is not a
`TextResponse`, even when the response has a textual or browser-renderable
`Content-Type` such as `application/json`, `application/xml`, or an image
type. This prevents users from viewing responses through the function or the
`scrapy view` command based on the response metadata that Scrapy already has.

## What Changes

- Determine the temporary file extension for a response from its `Content-Type`
  header when the response is not an `HtmlResponse`.
- Continue using the HTML-specific base URL injection and `.html` extension for
  `HtmlResponse`.
- Preserve the existing `.txt` fallback for textual responses without a more
  specific browser extension.
- Allow `scrapy view` to pass non-text responses to `open_in_browser()` instead
  of rejecting them before the utility can inspect their content type.

## Capabilities

### New Capabilities

- `open-in-browser`: Opening a Scrapy response in the local browser using the
  response type and `Content-Type` metadata.

### Modified Capabilities


## Impact

- `scrapy/utils/response.py`
- `scrapy/commands/view.py`
- `tests/test_utils_response.py`
- `tests/test_commands.py`
