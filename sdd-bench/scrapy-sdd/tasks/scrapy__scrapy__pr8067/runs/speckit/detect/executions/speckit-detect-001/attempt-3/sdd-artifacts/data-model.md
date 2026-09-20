# Phase 1 Data Model: Browser Preview for Non-Text Responses

This feature introduces no persisted entities. The model below describes the
in-memory objects and the transformation the feature implements.

## Entity: Response (existing)

| Field | Type | Notes |
|-------|------|-------|
| `body` | `bytes` | Written verbatim to the preview file (FR-009). |
| `headers` | mapping | `Content-Type` is the media-type source for the extension (FR-002). |
| response class | `type[Response]` | Selects the enrichment path: HTML, text, or other. |

**Classification rule**

- `HtmlResponse` -> HTML path.
- any other `TextResponse` -> text path.
- any other `Response` -> media-type path (new).

## Entity: MediaTypeToExtension (new rule)

| Input | Output | Rule |
|-------|--------|------|
| raw `Content-Type` value | media type | Parameters after `;` are dropped; value is decoded/normalized. |
| media type | registered extension | Standard-library registry lookup. |
| media type with no entry | fallback extension | Generic suffix used when nothing matches (FR-005). |
| missing/empty header | fallback extension | Same fallback; no exception (SC-003). |

**Validation rules**

- The result MUST always be a non-empty suffix suitable for `tempfile.mkstemp`.
- Lookup MUST NOT raise for unknown or malformed media types.

## Entity: PreviewFile (new artifact, ephemeral)

| Field | Type | Notes |
|-------|------|-------|
| path | `str` | Created via `tempfile.mkstemp(ext)`. |
| extension | `str` | `.html` / `.txt` / media-type derived / fallback. |
| content | `bytes` | Exactly `response.body`; for HTML, body with the injected base tag. |
| opened URL | `str` | `file://{path}` passed to the opener. |

**State transitions**

1. `created` - `mkstemp` with the resolved extension.
2. `written` - full body written and file descriptor closed.
3. `opened` - `file://` URL handed to `_openfunc`; the returned value is
   propagated to the caller.

No deletion state is defined: the temporary file intentionally outlives the
call so the browser can load it, matching existing behavior.
