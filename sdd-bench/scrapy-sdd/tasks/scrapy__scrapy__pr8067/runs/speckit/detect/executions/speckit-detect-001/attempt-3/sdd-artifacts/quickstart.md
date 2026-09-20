# Quickstart Validation: Browser Preview for Non-Text Responses

Validation only - no implementation or test code lives here. Commands assume the
repository root and an installed development environment.

## Prerequisites

- The repository checked out at the feature branch.
- The project's standard development environment for running its Python test
  suite and its `scrapy` CLI entry point.

## Scenario 1 - Helper accepts a non-text response

1. In a Python session, build a plain `Response` with a binary body and a
   `Content-Type` header of `image/png`.
2. Call the preview helper with a recording opener that captures the file URL
   and reads the file it points at.

**Expected**: no exception; the captured path ends in `.png`; the file bytes
equal `response.body` byte for byte.

## Scenario 2 - Unknown media type falls back instead of failing

1. Repeat Scenario 1 with (a) no `Content-Type` header and (b) a media type such
   as `application/x-scrapy-unknown`.

**Expected**: both calls open a file using the documented fallback suffix; no
exception is raised; bodies are preserved.

## Scenario 3 - Existing previews are unchanged

1. Preview an `HtmlResponse` containing a doctype, HTML comments, and an
   existing `<base>` tag.
2. Preview a plain text response.

**Expected**: the HTML file still contains exactly one injected base tag placed
after the doctype, comments are preserved, and the file ends in `.html`; the
plain text file ends in `.txt`.

## Scenario 4 - `scrapy view` opens a non-text URL

1. Start the project's local test server route that serves a non-text body.
2. Point the `BROWSER` environment variable at a script that records the URL it
   receives, then run `scrapy view <non-text-url>`.
3. Fetch the recorded `file://` URL.

**Expected**: exit code 0, no `Cannot view a non-text response.` message, and
the recorded file contains the served bytes.

## Scenario 5 - HTML command path regression check

1. With the same recording browser, run `scrapy view <html-url>`.

**Expected**: unchanged behavior - the preview file contains the scraped HTML
with the injected base tag, and the exit code is 0.

## References

- Behavior contract: [contracts/open_in_browser.md](contracts/open_in_browser.md)
- Transformation details: [data-model.md](data-model.md)
