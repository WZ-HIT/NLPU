# Spec: Support non-text responses in open_in_browser via Content-Type

Source task: `/task-input/task.md` (PR `scrapy/scrapy#8067`, base
commit `3857c6906b2da51e12ca6005434512b7704fd659`).

## Problem

`scrapy.utils.response.open_in_browser()` only supports `HtmlResponse` and
`TextResponse`; any other `Response` raises `TypeError: Unsupported response
type`. The `scrapy view` command additionally blocks non-`TextResponse`
objects in `scrapy.commands.view.Command._print_response` with
`Cannot view a non-text response.`, so fetched binary content such as images
or PDFs cannot be opened in a browser.

## Required behavior

1. `open_in_browser()` continues to write `HtmlResponse` bodies with an
   `.html` extension and to inject the `<base>` tag as it does today.
2. `open_in_browser()` continues to write non-HTML `TextResponse` bodies with
   a `.txt` extension.
3. For a non-text `Response`, `open_in_browser()` derives the temporary file
   extension from the response `Content-Type` header (for example
   `image/png` -> `.png`, `application/pdf` -> `.pdf`) instead of raising
   `TypeError`, so the browser can render the content.
4. Unknown or missing `Content-Type` values must fall back to a defined
   default rather than failing.
5. The command-level non-text guard is expected to be lifted so the `view`
   command benefits from the same behavior.

## Affected production symbols

- `scrapy.utils.response.open_in_browser` (primary change).
- `scrapy.commands.view.Command._print_response` (command-level gate that
  delegates to `open_in_browser`).

## Planning constraints

- Planning only: no tests were executed and no project code or test files
  were modified.
- Candidate test files are recorded in `detection-draft.json` in this same
  planning directory.
