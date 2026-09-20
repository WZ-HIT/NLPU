# Phase 1 Data Model: Deterministic Response-Based File Path Test

This feature changes a test, so the "entities" below are the in-test values and
doubles that carry the behavior. No production data model changes.

## Store record (`StatInfo` as returned by the mocked `stat_file`)

| Field | Type | Notes |
|-------|------|-------|
| `checksum` | `str` | Fixed dummy value in the test; presence forces the up-to-date branch to be considered. |
| `last_modified` | `float` (epoch seconds) | **The field being corrected.** Must be a timestamp unambiguously in the past so the computed age is positive on every platform. |

- Validation rule: `now - last_modified > 0` must hold for any realistic host
  clock reading taken after the mock is installed.
- Relationship: consumed by `FilesPipeline._onsuccess` via `result.get("last_modified")`.

## Response-aware pipeline double

| Aspect | Description |
|--------|-------------|
| Base | `FilesPipeline` |
| Override | `file_path(request, response, info, *, item)` appends the extension guessed from the response `Content-Type` header when a response is present. |
| Configuration | `FILES_EXPIRES = 0` so the up-to-date check cannot short-circuit before the download. |

- Validation rule: with no response, the path is unchanged; with a response,
  the returned path ends in the response-derived extension.

## Item result entry (`FileInfoOrError` payload)

| Field | Type | Notes |
|-------|------|-------|
| `status` | `str` | Expected `"downloaded"`; the flake produced `"uptodate"`. |
| `path` | `str` | Expected to end with `.pdf`, proving the response-derived path was used. |

- State transition: `request prepared → store freshness check → (re)download →
  item completed`.
- Invariant: with expiry disabled and a stale pre-existing file, the freshness
  check MUST NOT resolve the entry to `uptodate`.

## Files touched

| Path | Role |
|------|------|
| `tests/test_pipeline_files.py` | Contains `TestFilesPipeline.test_file_path_from_response`; the only file whose test data changes. |
| `scrapy/pipelines/files.py` | Read-only reference for `_onsuccess` and `file_path` semantics. |
| `scrapy/pipelines/media.py` | Read-only reference for the shared `media_to_download` flow. |
| `tests/utils/media_pipelines.py`, `tests/utils/decorators.py` | Reused helpers; unchanged. |
