# Feature Specification: Browser Preview for Non-Text Responses

**Feature Branch**: `speckit-detect`

**Created**: 2026-09-17

**Status**: Draft

**Input**: User description: "Support non-text responses in open_in_browser via Content-Type" (scrapy/scrapy PR #8067, resolves scrapy/scrapy issue #3902)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preview a non-text response from spider code (Priority: P1)

A developer debugging a spider calls `open_in_browser(response)` for a response
whose body is not text (an image, a PDF, an archive, a binary blob). Today
Scrapy refuses: `scrapy.utils.response.open_in_browser` raises
`TypeError: Unsupported response type: Response`. The developer needs the raw
bytes written to a temporary file whose name carries an extension derived from
the response `Content-Type`, so that the local browser/desktop opens it with the
right application instead of showing a broken text preview.

**Why this priority**: This is the entire request. Without it the public helper
is unusable for exactly the resources it is most useful for (images, PDFs), and
the linked issue stays open.

**Independent Test**: Call `open_in_browser` with a non-text `Response` whose
headers declare a concrete media type (for example `image/png`) and a recording
opener function; assert that no exception is raised, that the opened path ends
with the extension registered for that media type, and that the file content
equals `response.body`.

**Acceptance Scenarios**:

1. **Given** a `Response` with `Content-Type: image/png`, **When**
   `open_in_browser(response)` is called, **Then** a temporary file with a
   `.png` extension is written with the response body and passed to the opener.
2. **Given** an `HtmlResponse`, **When** `open_in_browser(response)` is called,
   **Then** behavior is unchanged: `<base href="...">` is injected after any
   doctype, and the file uses a `.html` extension.
3. **Given** a plain `TextResponse` (for example `text/plain`), **When**
   `open_in_browser(response)` is called, **Then** behavior is unchanged: the
   file uses a `.txt` extension.

---

### User Story 2 - `scrapy view` opens non-text resources (Priority: P2)

Running `scrapy view <url>` against a URL that returns a non-text body currently
logs `Cannot view a non-text response.` and exits without opening anything, even
though the user explicitly asked to look at what the spider sees. The command
must forward the fetched response to `open_in_browser` and let the browser
handle it.

**Why this priority**: The `view` command is the user-facing entry point of the
same capability; it is the CLI surface named in the linked issue. It is lower
priority than the helper because the helper is the reusable primitive.

**Independent Test**: Run `scrapy view` against a local server route that serves
a non-text body, with a fake `BROWSER` script; assert exit code 0 and that the
recorded file URL points at the fetched bytes.

**Acceptance Scenarios**:

1. **Given** a URL serving a non-text body, **When** `scrapy view` is run,
   **Then** the command succeeds and the browser is opened with the downloaded
   body instead of printing an error.
2. **Given** a URL serving HTML, **When** `scrapy view` is run, **Then** the
   existing behavior (open the scraped page, `--spider`/`--no-redirect`
   options) is unchanged.

---

### User Story 3 - Deterministic fallback when the media type is unusable (Priority: P3)

Some responses carry no `Content-Type` header, or a media type that has no
registered file extension. The helper must still produce a preview file rather
than failing.

**Why this priority**: It is a robustness edge case; the common path (a
well-formed media type) already delivers the value.

**Independent Test**: Call `open_in_browser` with a `Response` that has no
`Content-Type` header and with one that has an unknown media type; assert that
both calls open a file with the documented fallback extension and that the body
bytes are preserved.

**Acceptance Scenarios**:

1. **Given** a `Response` with no `Content-Type` header, **When**
   `open_in_browser` is called, **Then** a preview file is still created and
   opened.
2. **Given** a `Response` with a media type that maps to no known extension,
   **When** `open_in_browser` is called, **Then** a preview file is still
   created and opened.

---

### Edge Cases

- `Content-Type` carrying parameters, e.g. `image/svg+xml; charset=utf-8` — the
  media type must be parsed out and the parameters ignored.
- Media types with `+xml`/`+json` suffixes that have no extension entry.
- Missing `Content-Type` header, or an empty header value.
- Empty response body: a valid but empty preview file must still be produced.
- Content types that map to multiple candidate extensions, which must not make
  the result ambiguous or crash.
- HTML-specific guarantees must not regress: doctype ordering before the
  injected base tag, preservation of HTML comments, a single base tag, and
  linear-time matching for adversarial bodies.
- Behaviors that depend on the temporary file having the right suffix (browser
  association, Windows path handling) must keep working for the new extensions.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `open_in_browser` MUST accept every `Response` subclass, including
  non-text responses, and MUST NOT raise a type error for them.
- **FR-002**: For non-text responses the preview file extension MUST be derived
  from the response `Content-Type` media type.
- **FR-003**: HTML responses MUST keep their current treatment: base-tag
  injection after any doctype, `.html` extension, unchanged single-insertion
  semantics and unchanged resistance to adversarial input.
- **FR-004**: Plain text responses (for example `text/plain`) MUST keep using a
  `.txt` extension.
- **FR-005**: When no extension can be derived from the response (missing or
  unknown `Content-Type`), the helper MUST fall back to a generic extension and
  still open the file rather than failing.
- **FR-006**: `scrapy view` MUST pass non-text responses to `open_in_browser`
  and MUST NOT abort with the `Cannot view a non-text response.` error.
- **FR-007**: The public signature `open_in_browser(response, _openfunc=...)`
  MUST remain backward compatible, and the helper MUST remain importable from
  `scrapy.utils.response`.
- **FR-008**: The change MUST NOT introduce a new third-party runtime
  dependency.
- **FR-009**: The written preview file MUST contain exactly `response.body`,
  byte for byte.
- **FR-010**: `scrapy shell`'s `view` variable, which binds the same helper,
  MUST keep working for text responses and MUST also accept non-text ones.

### Key Entities

- **Response**: the object passed to the helper; provides `body` (bytes) and
  `headers` (including `Content-Type`), and determines which enrichment path
  applies (HTML, text, other).
- **Content-Type to extension mapping**: the rule set that converts a media type
  such as `image/png` into the file suffix used for the temporary preview file.
- **Preview file**: the temporary artifact written to disk and handed to the
  browser opener; identified by its path/URL and suffix.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of non-text responses with a recognizable media type open a
  preview file whose suffix matches that media type, verified across at least
  three distinct media families (image, document, archive/octet-stream).
- **SC-002**: 0 regressions in existing browser-preview behavior: every
  pre-existing HTML/text preview scenario still passes unchanged.
- **SC-003**: 0 crashes/exceptions for responses with a missing, empty, or
  unknown `Content-Type`; all such cases produce an opened preview file.
- **SC-004**: `scrapy view` returns success and opens the fetched bytes for a
  non-text URL, where it previously reported an error in 100% of such runs.
- **SC-005**: Users can preview any fetched resource without writing custom
  file-handling code: one call to the helper, or one CLI invocation, is
  sufficient.

## Assumptions

- The `Content-Type` header of the response is the authoritative signal for the
  file type; content sniffing of the body is out of scope.
- Extension lookup uses the standard-library media-type registry already
  available to the project; a new dependency is unnecessary and undesired.
- The set of well-known textual media types continues to map to a `.txt`
  preview, since a text preview is the existing contract for those.
- Only local rendering is in scope: the files are still opened through the
  configured browser opener (`webbrowser.open` by default), and no download or
  export behavior is added.
- Existing user-facing behavior of `scrapy view` for HTML pages (redirect
  handling, spider selection, logging) must be preserved.
