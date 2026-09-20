# Implementation Plan

- [ ] 1. Locate every test file that references the twisted HTTP/2 handler
  surface.
- [ ] 1.1 Search tests for the handler class name, the handler module path, the
  `DOWNLOAD_HANDLERS` string path, and the `scrapy.core.http2` package.
  - Confirm hits in `tests/test_downloader_handler_twisted_http2.py` (class
    import, settings string, `scrapy.core.http2.stream` caplog/patch target).
  - Confirm hits in `tests/test_http2_client_protocol.py` (direct
    `scrapy.core.http2.protocol` / `.stream` imports and patch targets).
  - Confirm shared coverage in `tests/utils/bases/download_handlers_http.py`.
  - _Requirements: 3.1, 3.2_

- [ ] 2. Record the detection draft.
- [ ] 2.1 Write exactly one `detection-draft.json` in the planning directory
  containing only a `candidates` array of `{path, symbols, reason}` objects.
  - Each `path` is a repository-relative test path.
  - No test execution, no writes outside `.kiro/specs/`.
  - _Requirements: 3.1, 3.2, 3.3_

- [ ] 3. Capture spec-level context for the change. (Completed in this phase.)
- [ ] 3.1 Record requirements, design, and this task list under the spec
  directory.
  - _Requirements: 1.1, 1.2, 2.1_
