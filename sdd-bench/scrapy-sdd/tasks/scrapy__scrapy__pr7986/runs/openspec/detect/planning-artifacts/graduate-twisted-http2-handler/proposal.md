## Why

The Twisted-based HTTP/2 download handler has been available long enough to
graduate from experimental status (scrapy/scrapy#5047), but its class and module
paths are still presented as public API. Publishing it as a supported,
documented handler while keeping its implementation private avoids promising
API stability that the project does not intend.

## What Changes

- Remove the experimental warning from the Twisted-based HTTP/2 download
  handler documentation and describe it as a supported handler.
- **BREAKING** Privatize the handler's implementation API by exposing it through
  private module/class paths; update the documented `DOWNLOAD_HANDLERS` example
  and all current documentation references accordingly.
- Update internal imports and tests to use the private paths.
- Keep existing HTTP/2 behavior unchanged: HTTPS requests, connection pooling,
  TLS settings, bind addresses, timeouts, and response handling continue as
  before.

## Capabilities

### New Capabilities

None. This is a documentation and API-surface refactor of an existing
implementation, with no newly specified runtime behavior.

### Modified Capabilities

None. The handler's externally observable request/response behavior is not
changing; only its published API location and experimental labeling change.

## Impact

- `scrapy/core/downloader/handlers/http2.py` and the internal
  `scrapy/core/http2/` implementation package, if the private-path migration
  includes them.
- `scrapy/core/downloader/contextfactory.py` references.
- Current user documentation in `docs/topics/download-handlers.rst`,
  `docs/topics/asyncio.rst`, `docs/topics/settings.rst`,
  `docs/topics/downloader-middleware.rst`, and `docs/faq.rst`.
- HTTP/2 handler tests, especially
  `tests/test_downloader_handler_twisted_http2.py`; protocol tests may also
  require import updates if the internal package is moved.
- Users configuring the handler by import path must adopt the new private path.
  Historical release notes remain historical records and are not rewritten.
