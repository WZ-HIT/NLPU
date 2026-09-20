# Data Model: Open Non-Text Responses in Browser via Content-Type

## Overview

This feature has no persistent data model. Its planning model describes the response facts used to choose a local-file extension and the temporary browser target produced from those facts.

## Entity: Browser Open Request

**Description**: A user request to open a response in a browser.

**Fields**:

- `response`: The response object to open.
- `open_function`: The optional injection point used by tests and callers; defaults to the normal system browser opener.

**Validation rules**:

- A response must expose a URL, headers, and a raw body.
- The body must be bytes.
- The response must be supported by one of the extension-resolution paths.

## Entity: Response Classification

**Description**: The precedence category that determines how the response body is prepared.

**Values**:

- `html`: An HTML response. The body receives base-link correction and uses `.html`.
- `text`: A non-HTML textual response. The body is written unchanged and uses `.txt`.
- `generic`: Any other response. Extension selection depends on `Content-Type`.

**Validation rules**:

- Classification is deterministic for a response instance.
- HTML and text classifications take precedence over generic `Content-Type` mapping.

## Entity: Media Type Declaration

**Description**: The effective `Content-Type` information for a generic response.

**Fields**:

- `raw_value`: The effective header value, or absent.
- `media_type`: The portion before the first semicolon after trimming and case normalization.
- `parameters`: Any remaining header text; not used for extension selection.
- `extension`: The conventional extension resolved from `media_type`, or unresolved.

**Validation rules**:

- Parameters do not affect extension lookup.
- ASCII case differences and surrounding whitespace do not affect lookup.
- An absent, malformed, or unknown media type is unresolved.

## Entity: Browser Target

**Description**: The temporary local file path passed to the browser opener.

**Fields**:

- `local_path`: The generated temporary file path.
- `extension`: The resolved local-file suffix.
- `body`: The exact bytes written to the file.

**Validation rules**:

- The extension must be determined by response classification and, for generic responses, the media type.
- The URL suffix must not override the selected extension.
- The body must be byte-identical to the response body.
- The browser opener must not be called when extension resolution fails.

## State Transitions

1. Receive a response.
2. Classify it as HTML, text, or generic.
3. Resolve an extension:
   - HTML to `.html`.
   - Text to `.txt`.
   - Generic to the conventional extension for its normalized media type.
4. If resolution fails, report an unsupported-response error and stop.
5. Create a temporary file with the resolved extension.
6. Write the exact body bytes.
7. Pass the local file path to the browser opener.

## Relationships

- One browser open request has one response.
- One response has one classification.
- A generic response has zero or one effective media type declaration.
- A successful resolution produces one browser target.
- An unresolved media type produces no browser target and no browser-opener call.
