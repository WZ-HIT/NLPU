# Phase 0 Research: Browser Preview for Non-Text Responses

**Feature**: Support non-text responses in `open_in_browser` via `Content-Type`
**Base commit**: `3857c6906b2da51e12ca6005434512b7704fd659`

## Current behavior (evidence from the repository)

- `scrapy/utils/response.py::open_in_browser` writes `response.body` to a
  temporary file created with `tempfile.mkstemp(ext)` and then calls the opener.
  `ext` is `.html` for `HtmlResponse` (after injecting a `<base href="...">`
  tag) and `.txt` for any other `TextResponse`. Everything else raises
  `TypeError(f"Unsupported response type: {response.__class__.__name__}")`.
- `scrapy/commands/view.py::_print_response` refuses non-text responses:
  `if not isinstance(response, TextResponse): logger.error("Cannot view a non-text response.")`.
- `scrapy/shell.py` exposes the same helper as the `view` shell variable.
- Existing coverage: `tests/test_utils_response.py` (`test_open_in_browser`,
  `test_open_in_browser_text_response_uses_txt_extension`,
  `test_open_in_browser_raises_for_unsupported_response_type`) and
  `tests/test_commands.py::TestViewCommand` (`test_view`,
  `test_non_text_response`, which asserts the refusal message).

## Decision 1 - Extension source for non-text responses

**Decision**: Derive the preview file suffix from the response `Content-Type`
media type, using the standard-library media-type/extension registry that ships
with the interpreter, with parameters (`; charset=...`) stripped before lookup.

**Rationale**: `Content-Type` is the only type information guaranteed to be
present on every `Response` regardless of subclass, it is already used elsewhere
in the codebase for response classification, and the standard library registry
needs no new dependency.

**Alternatives considered**:

- **Keep raising `TypeError` for non-text responses**: rejected; that is the
  defect being fixed (issue #3902).
- **Sniff the body bytes** (for example via the existing binary/text heuristic):
  rejected as the primary signal. It cannot distinguish PNG from JPEG from PDF,
  which is exactly the information the browser needs, and it would add cost on
  large bodies.
- **Reuse the response-class registry (`scrapy.responsetypes.ResponseTypes`)**:
  rejected. It maps media types to `Response` *classes*, not to file
  extensions, and only covers the small `CLASSES` table; it would still leave
  `image/png` and friends without an extension.
- **Hardcode a small media-type to extension table**: rejected. It duplicates
  data the interpreter already provides and would need constant maintenance.

## Decision 2 - Fallback when no extension can be derived

**Decision**: When the header is missing, empty, unparsable, or maps to no known
extension, use a single documented generic suffix and still open the file.

**Rationale**: The user asked to *see* the resource; refusing to open it because
the media type is exotic would reintroduce the failure mode this feature
removes. A single fallback also keeps the helper deterministic and testable.

**Alternatives considered**: raising on unknown media types (rejected -
regression in usability); defaulting unknown binary types to `.txt` (rejected -
misleading, may make the browser render garbage); writing with no extension at
all (rejected - breaks Windows/browser association and makes the preview file
harder to identify).

## Decision 3 - Preserve existing HTML and text behavior

**Decision**: Leave the `HtmlResponse` path (base-tag injection, doctype
ordering, comment preservation, `.html`) and the `TextResponse` `.txt` path
exactly as they are; only the previously-raising branch changes.

**Rationale**: The HTML path carries security-sensitive guarantees that recent
changes deliberately hardened (single base tag, comment handling, linear-time
matching for adversarial bodies). Touching it would put those guarantees at
risk for no user benefit.

**Alternatives considered**: unifying all responses under a single
extension lookup (rejected - HTML responses would lose the base tag that makes
relative links resolve, and text responses would change their established
preview type).

## Decision 4 - `scrapy view` behavior

**Decision**: Remove the non-text refusal in `scrapy/commands/view.py` so the
command forwards any fetched response to the helper.

**Rationale**: The command's contract is "open the URL in a browser, as seen by
Scrapy"; the refusal makes `scrapy view` unable to inspect the very resources a
spider downloads. Failure to open should be surfaced by the underlying helper or
the operating system, not by a blanket type check.

**Alternatives considered**: adding a CLI flag to opt into non-text previews
(rejected - extra surface area for what users already expect to work); leaving
the command as-is and documenting the Python helper only (rejected - leaves the
CLI half of the reported issue unsolved).

## Open questions

None. The technical context below is fully resolved; no `NEEDS CLARIFICATION`
markers remain.
