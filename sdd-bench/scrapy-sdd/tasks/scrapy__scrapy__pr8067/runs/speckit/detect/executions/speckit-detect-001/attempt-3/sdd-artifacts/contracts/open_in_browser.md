# Phase 1 Contract: Browser Preview Interfaces

## Contract 1 - Python helper `scrapy.utils.response.open_in_browser`

```python
def open_in_browser(
    response: Response,
    _openfunc: Callable[[str], Any] = webbrowser.open,
) -> Any: ...
```

**Guarantees**

1. Accepts any `Response` instance; MUST NOT raise `TypeError` for non-text
   responses (FR-001).
2. Writes `response.body` byte-for-byte to a temporary file (FR-009); for
   `HtmlResponse` the written bytes additionally contain one injected
   `<base href="...">` tag placed after any doctype.
3. File suffix: `.html` for HTML, `.txt` for other text responses, the
   extension derived from the `Content-Type` media type otherwise, and a
   documented generic suffix when no extension can be derived (FR-002, FR-004,
   FR-005).
4. Calls `_openfunc(f"file://{path}")` exactly once and returns its result,
   preserving the existing injection point used by tests and by the shell.
5. Signature and import path are unchanged (FR-007).

**Error behavior**

- Missing, empty, or unknown `Content-Type`: no error; fallback suffix.
- Body writing errors propagate unchanged (unchanged from today).

## Contract 2 - CLI `scrapy view <url>`

```text
scrapy view [--spider=SPIDER] [--no-redirect] <url>
```

**Guarantees**

1. Fetches the URL through the downloader exactly as before and invokes the
   preview helper on the resulting response regardless of whether it is a text
   response (FR-006).
2. MUST NOT emit `Cannot view a non-text response.` and MUST NOT skip opening
   the resource.
3. Exit status, logging, spider selection, and redirect handling for HTML
   responses are unchanged.

## Contract 3 - Shell binding

- `scrapy shell` continues to expose the helper as the `view` variable; the
  same guarantees as Contract 1 apply (FR-010).
