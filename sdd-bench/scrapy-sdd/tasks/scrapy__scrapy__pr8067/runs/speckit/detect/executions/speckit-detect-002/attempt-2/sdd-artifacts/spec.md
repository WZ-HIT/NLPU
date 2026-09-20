# Feature Specification: Open Non-Text Responses in Browser via Content-Type

**Feature Branch**: `001-open-in-browser-content-type`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "Pull request 8067: Support non-text responses in open_in_browser via Content-Type. Resolves scrapy/scrapy issue 3902."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Open a downloaded non-text response in a browser (Priority: P1)

A developer debugging a crawl opens a downloaded response whose body is binary, such as a PNG image or a PDF document. The browser receives a local file whose extension reflects the response media type, so the operating system or browser can render the file correctly.

**Why this priority**: This is the missing user capability described by issue 3902 and the primary reason for the change.

**Independent Test**: Create a generic response with binary content and a supported `Content-Type`, call the public browser-opening utility with a recording opener, and verify that the opener receives a local file with the expected extension and byte-identical content.

**Acceptance Scenarios**:

1. **Given** a response containing PNG bytes and a `Content-Type` of `image/png`, **When** the user opens it in a browser, **Then** the browser is given a local file ending in `.png` whose body is byte-identical to the response body.
2. **Given** a response containing PDF bytes and a `Content-Type` of `application/pdf`, **When** the user opens it in a browser, **Then** the browser is given a local file ending in `.pdf`.
3. **Given** the command-line view workflow fetches an image resource with an `image/png` media type, **When** the workflow completes, **Then** it succeeds and the browser is given a local `.png` file instead of reporting that non-text responses cannot be viewed.

---

### User Story 2 - Preserve existing HTML and text behavior (Priority: P2)

A developer who opens an HTML or textual response continues to get the existing specialized behavior: HTML remains viewable with working relative links, and non-HTML text remains a text file.

**Why this priority**: The new binary-response path must not regress the established behavior that existing users depend on.

**Independent Test**: Re-run the existing HTML base-link and textual-response scenarios and verify that file extensions, injected base links, and body handling remain unchanged.

**Acceptance Scenarios**:

1. **Given** an HTML response, **When** it is opened in a browser, **Then** the local file still has an `.html` extension and contains exactly one effective base link appropriate for the response URL.
2. **Given** a non-HTML textual response, **When** it is opened in a browser, **Then** the local file still has a `.txt` extension.
3. **Given** HTML content with comments, doctypes, or existing base links, **When** it is opened in a browser, **Then** the existing placement and preservation rules still apply.

---

### User Story 3 - Fail clearly when the media type is unusable (Priority: P3)

A developer supplies a response without a usable `Content-Type`, or with a media type that has no known local-file extension. The operation reports a clear unsupported-response failure instead of silently opening a file with a misleading or unsafe extension.

**Why this priority**: Predictable failure protects users from opening the wrong kind of content and keeps the scope focused on responses whose type can be established.

**Independent Test**: Supply generic responses with no header, a malformed header, and an unknown media type, then verify that no browser opener is called and each case reports a clear unsupported-response error.

**Acceptance Scenarios**:

1. **Given** a generic response with no `Content-Type`, **When** the user attempts to open it, **Then** the operation fails with a clear unsupported-response error and does not call the browser opener.
2. **Given** a generic response with a syntactically invalid or unknown `Content-Type`, **When** the user attempts to open it, **Then** the operation fails clearly rather than choosing an arbitrary extension.
3. **Given** a supported media type with additional parameters, casing differences, or surrounding whitespace, **When** the user opens it, **Then** the parameters and formatting do not prevent correct extension selection.

---

### Edge Cases

- `Content-Type` includes parameters such as `image/png; charset=binary`; extension selection uses only the media type.
- The media type differs in case, such as `IMAGE/PNG`; extension selection remains correct.
- The response has an empty body; the browser still receives a file with the correct extension.
- The response URL has no extension or a misleading extension; the URL suffix does not override a usable `Content-Type`.
- A generic response declares an HTML media type. It receives an HTML extension through the media-type mapping, while specialized HTML base-link handling remains limited to actual HTML response objects.
- Multiple `Content-Type` values are present. The behavior remains deterministic and uses the effective response header value.
- A supported binary body must never be decoded as text or re-encoded before it is written.
- The temporary file lifecycle and existing performance safeguards remain unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The public browser-opening capability MUST accept a generic response when its `Content-Type` identifies a media type that can be mapped to a local-file extension.
- **FR-002**: The capability MUST derive the extension from the media type portion of `Content-Type`, ignoring parameters, surrounding whitespace, and ASCII case differences.
- **FR-003**: The capability MUST write the response body byte-for-byte without text decoding, replacement, or normalization.
- **FR-004**: The capability MUST resolve conventional local-file extensions for common browser-viewable media types, including `image/png`, `image/jpeg`, and `application/pdf`.
- **FR-005**: Existing HTML response behavior MUST remain unchanged, including the `.html` extension, base-link injection, comment preservation, doctype ordering, and existing performance protections.
- **FR-006**: Existing non-HTML textual response behavior MUST remain unchanged and continue to use a `.txt` extension.
- **FR-007**: For generic responses, `Content-Type` MUST take precedence over the response URL suffix and body contents when selecting an extension.
- **FR-008**: If `Content-Type` is absent, malformed, or maps to no usable extension, the capability MUST report a clear unsupported-response error and MUST NOT call the browser opener.
- **FR-009**: The command-line view workflow MUST delegate non-text responses to the browser-opening capability instead of rejecting every response that is not textual.
- **FR-010**: The change MUST NOT require new runtime dependencies, configuration, or user opt-in.
- **FR-011**: Existing supported HTML, text, and generic-binary behavior MUST remain covered by automated tests, including command-level coverage for viewing an image resource.

### Key Entities

- **Response**: The downloaded content to open. Its public attributes include URL, headers, and raw body.
- **Media type declaration**: The `Content-Type` header for a response. Its media type determines the local-file extension; its optional parameters do not.
- **Browser target**: The temporary local file passed to the browser. It has a selected extension and must contain the exact response bytes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In all covered PNG, JPEG, and PDF validation cases, 100% of browser targets use the expected conventional extension and preserve response bytes exactly.
- **SC-002**: All existing HTML base-link, comment-preservation, doctype, and performance scenarios continue to pass without changed expected behavior.
- **SC-003**: All non-HTML textual validation cases continue to produce `.txt` browser targets.
- **SC-004**: In all missing-header, malformed-header, and unknown-media-type cases, 100% report a clear unsupported-response failure and leave the browser opener uncalled.
- **SC-005**: The command-line view of an image resource succeeds and supplies a browser target ending in `.png`; the previous "Cannot view a non-text response" outcome occurs in zero image-viewing cases.
- **SC-006**: The focused utility and command-level test suites pass with no regression in previously supported behavior.

## Assumptions

- A response's declared `Content-Type` is the authoritative source for choosing a generic response's file extension.
- Standard operating-system or language-provided media-type mappings are acceptable; a custom extension registry is not required.
- Responses without a usable `Content-Type` remain unsupported, because no trustworthy extension can be selected.
- The scope is limited to opening already-downloaded responses. Fetching, browser selection, rendering behavior, and persistent file management remain unchanged.
- The public browser-opening utility and the command-line view workflow are the only user-facing entry points in scope; shell exposure of the utility benefits automatically.
- Temporary files remain subject to the existing lifecycle and are not deleted by this feature.
