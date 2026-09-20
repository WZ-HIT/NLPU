# Design Document

## Overview

This feature delivers two coordinated changes to the Twisted-based HTTP/2
download handler: removing its experimental status from user-facing
documentation, and privatizing the API surface it shares with the
`scrapy.core.http2` client package. Users who enable the handler through
`DOWNLOAD_HANDLERS` keep a working configuration path; maintainers gain
freedom to refactor the supporting package.

The detect stage does not implement the change. Its deliverable is a
`detection-draft.json` listing the candidate test files that exercise the
affected surface, together with the symbols inside them and the reason each
file is implicated.

### Goals

- Identify every test file that imports, configures, or patches the twisted
  HTTP/2 handler or its supporting client package.
- Keep the candidate list limited to repository-relative test paths.
- Keep all planning output inside the mounted planning directory.

### Non-Goals

- Editing `scrapy/**`, `tests/**`, or documentation.
- Running `pytest`, `tox`, or any other test command.

## Observed Evidence in the Base Commit

| Concern | Location in base commit |
| --- | --- |
| Handler implementation | `scrapy/core/downloader/handlers/http2.py` (`H2DownloadHandler`, `_ScrapyH2Agent`) |
| Supporting client package | `scrapy/core/http2/` (`agent.py`, `protocol.py`, `stream.py`) |
| Experimental warning text | `docs/topics/download-handlers.rst` (H2DownloadHandler section) |
| Experimental flag mechanism | `scrapy/core/downloader/handlers/_base_streaming.py` (`experimental` ClassVar, used by `_httpx.py`) |
| Handler tests | `tests/test_downloader_handler_twisted_http2.py` |
| Client-package tests | `tests/test_http2_client_protocol.py` |
| Shared handler test bases | `tests/utils/bases/download_handlers_http.py` |

The release metadata available in this environment shows the packaged
`scrapy/core/http2/` directory replaced by `scrapy/core/_http2/` in the next
shipped version, which is consistent with the "privatize its API" half of the
change.

## Design Decisions

1. **Detection scope is defined by references, not by module ownership.** A test
   file is a candidate when it names the handler class, the handler module
   path, the `DOWNLOAD_HANDLERS` string path, or the supporting client package.
2. **Shared test bases count as candidates when they encode handler behavior.**
   `tests/utils/bases/download_handlers_http.py` defines the behavioral contract
   reused by the twisted HTTP/2 test class, so a handler-API change can require
   updating it even though it names no module directly.
3. **No ranking beyond relevance.** Candidates are ordered by directness of the
   reference to the changed surface.

## File Structure Plan

```
.kiro/specs/
├── detection-draft.json                              # detect-stage deliverable
└── twisted-http2-handler-api-privatization/
    ├── spec.json
    ├── requirements.md
    ├── design.md
    └── tasks.md
```

No file outside `.kiro/specs/` is written by this spec.

## Risks

- **Wrong granularity**: if the privatization renames only the handler class
  and not the supporting package, the client-package tests become a weaker
  candidate. The draft keeps them because the supporting package is referenced
  from the handler tests either way.
- **Documentation-only change**: if the change turned out to be docs-only, no
  test file would be affected; the draft records the reasoning so the miss is
  auditable.
