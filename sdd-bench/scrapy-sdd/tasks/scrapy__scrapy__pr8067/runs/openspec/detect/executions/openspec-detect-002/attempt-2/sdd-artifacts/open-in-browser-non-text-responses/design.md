## Context

See proposal.md — Why. At the base commit `scrapy/utils/response.py` resolves the temporary file
suffix by response class: `HtmlResponse` → `.html` (with `base` tag injection), `TextResponse` →
`.txt`, anything else → `TypeError`. `scrapy/commands/view.py` pre-empts that `TypeError` with a
`TextResponse` check that logs "Cannot view a non-text response.". The media type is already
available in `response.headers[b"Content-Type"]`, and `scrapy/pipelines/files.py` already uses
`mimetypes.guess_extension()` for the same kind of decision.

## Goals / Non-Goals

- Goal: any response Scrapy can fetch can be opened in a browser from `open_in_browser()`,
  `scrapy view`, and the shell `view()` helper.
- Non-goal: changing how HTML responses are rewritten, or making the temporary file names
  meaningful beyond their suffix.
- Non-goal: adding a download/export feature; the temporary file is still left on disk for the
  browser to read, exactly as today.

## Decisions

- Derive the suffix from `Content-Type` with the standard-library `mimetypes` module rather than
  from a hard-coded media type table, because Scrapy already depends on that module for the same
  purpose in `scrapy/pipelines/files.py` and it covers the media types users hit in practice.
  Alternative considered: extending `scrapy/responsetypes.py` (that module maps media types to
  response classes, not to file suffixes, and does not cover binary types well).
- Parse the header defensively: take the part before the first `;`, strip whitespace, and
  lower-case it, so `text/html; charset=utf-8` and `Application/PDF` both resolve.
- Fall back to `.bin` when the header is missing or the media type is unknown. Alternative
  considered: keep raising `TypeError` for unresolvable media types. Rejected because debugging
  helpers should show whatever the spider received, servers frequently omit or garble
  `Content-Type`, and the CLI path would otherwise still crash for such sites.
- Remove the `TextResponse` guard in `scrapy/commands/view.py` instead of extending it, so the
  command and the library share a single decision point and cannot drift apart.
- Keep the `HtmlResponse` branch first: HTML still needs the `base` tag injection and must not be
  treated as an opaque payload.

## Risks / Trade-offs

- [A browser may sniff or ignore the suffix for some media types] → the suffix only affects the
  temporary file; the body is written unchanged, which is what the browser inspects.
- [`mimetypes` results are platform dependent] → the fallback keeps behavior defined on every
  platform, and tests assert a small set of well-known media types.
- [Callers that caught `TypeError` from `open_in_browser()`] → documented as a breaking change in
  the proposal and release notes.

## Migration Plan

Single release, no data migration. Release notes record the behavior change; revert is a plain
source revert since no persisted state is involved.

## Open Questions

None that affect the specs, the approach, or the tasks.
