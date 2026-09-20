## Why

`scrapy.utils.response.open_in_browser()` — and the `scrapy view` command and the shell
`view(response)` helper built on it — only work with text responses. A `Response` whose body is
not text (an image, a PDF, a compressed archive) is rejected with
`TypeError: Unsupported response type: Response`, and `scrapy view` prints "Cannot view a
non-text response." Browsers render those payloads natively, and the response's `Content-Type`
header already identifies the media type, so the temporary file created for the browser can
carry a matching file suffix. This resolves issue #3902.

## What Changes

- `open_in_browser()` accepts any `Response`, not only `TextResponse`. For non-text responses it
  chooses the temporary file suffix from the media type in the `Content-Type` header (for
  example `image/png` → `.png`, `application/pdf` → `.pdf`). Media type parameters such as
  `; charset=...` are ignored and the media type lookup is case-insensitive. When the header is
  missing or the media type is unknown, the body is written with a generic `.bin` suffix and the
  response is still opened, instead of raising an error.
- HTML responses keep their current behavior: the `<base>` tag is injected into the body and the
  suffix is `.html`. Other text responses keep the `.txt` suffix.
- `scrapy view` no longer refuses non-text responses: the "Cannot view a non-text response."
  guard is removed so the command delegates every response to `open_in_browser()`.
- Documentation of `open_in_browser()` and `scrapy view` describes the Content-Type-based
  suffix and the removal of the non-text restriction.
- **BREAKING**: `open_in_browser()` no longer raises `TypeError` for non-text responses. Code that
  relied on that exception to detect an unsupported response must be updated; the call now
  succeeds and returns whatever the open function returns.

## Capabilities

### New Capabilities

- `open-in-browser`: opening a fetched response in a local browser, including non-text responses,
  through `scrapy.utils.response.open_in_browser()` and its `scrapy view` / shell `view()`
  entry points.

### Modified Capabilities

None. The repository has no existing capability specs (`openspec/specs/` is empty), so no
existing requirement changes.

## Impact

- `scrapy/utils/response.py`: `open_in_browser()` accepts `Response`, resolves the file suffix
  from the response `Content-Type`, and stops raising `TypeError` for non-text bodies.
- `scrapy/commands/view.py`: drops the `TextResponse` check and the accompanying
  "Cannot view a non-text response." log message.
- Docs: `docs/topics/commands.rst`, `docs/topics/debug.rst`, `docs/topics/shell.rst`, and a
  release note in `docs/news.rst`.
- Tests: `tests/test_utils_response.py` (extension selection for binary, text, and HTML
  responses) and `tests/test_commands.py` (`TestViewCommand`, which currently asserts the
  non-text rejection).
- No new dependency: extension resolution uses the standard-library `mimetypes` module, as
  `scrapy/pipelines/files.py` already does.
