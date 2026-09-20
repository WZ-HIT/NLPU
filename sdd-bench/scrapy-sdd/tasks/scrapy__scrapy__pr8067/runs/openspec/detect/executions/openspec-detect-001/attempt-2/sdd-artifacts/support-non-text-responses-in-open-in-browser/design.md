## Context

See `proposal.md` for motivation. The current utility handles HTML responses
with base-URL injection and text responses with a `.txt` file, then rejects
other response objects. The `view` command also rejects non-text responses
before the utility runs.

## Goals / Non-Goals

**Goals:**

- Derive a browser-friendly file extension from `Content-Type` for non-HTML responses.
- Preserve existing HTML base-URL behavior and the `.txt` text fallback.
- Let `scrapy view` use the utility for non-text responses.

**Non-Goals:**

- Change response-class selection, content decoding, or downloader behavior.
- Add content sniffing when `Content-Type` is absent or unknown.
- Change the HTML base-tag algorithm.

## Decisions

- Parse the media type from `Content-Type`, ignoring parameters such as
  `charset`, and map it with the standard-library MIME type table. This keeps
  the mapping data-driven and covers images, PDFs, JSON, and similar formats.
- Handle `HtmlResponse` first so base-tag injection and `.html` output remain
  unchanged. Handle text responses with the existing `.txt` fallback so current
  behavior is preserved. For other responses, use the mapped extension; raise
  `TypeError` when no extension can be determined.
- Remove the command-level text-only guard and let the utility remain the single
  authority on whether a response can be opened. The utility's explicit error
  remains available for responses without usable type information.

## Risks / Trade-offs

- MIME mappings can vary across platforms, so the behavior is intentionally
  limited to types known to the running Python environment.
- Opening arbitrary non-text content in a browser depends on browser support;
  the command still returns the temporary path through the existing opener.

