# Phase 0 Research

## Search Strategy

**Decision**: Search the read-only repository for the exact marker
`DirtyReactorAggregateError`, then inspect each match to identify the enclosing
test and the conditional skip.

**Rationale**: The pull-request title names the marker exactly, making a literal
repository search the highest-signal and least speculative method.

**Alternatives considered**: Searching every skip in the suite was rejected as
too broad; inspecting the whole downloader test tree was unnecessary once the
marker produced a complete match set.

## Findings

**Decision**: Treat `tests/test_downloader_handler_twisted_ftp.py` as a
candidate because `TestFTP.test_invalid_credentials` conditionally skips on
Windows with asyncio.

**Decision**: Treat `tests/utils/bases/download_handlers_http.py` as a candidate
because `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd` and
`TestHttpBase.test_timeout_download_from_spider_server_hangs` contain conditional
skips for the same marker.

**Rationale**: These are the only three marker occurrences under `tests/`.

**Alternatives considered**: Concrete HTTP subclasses inherit the two base
methods, but the update-stage source of truth is the base file containing the
skip. Listing every subclass would broaden the candidate set beyond the files
that carry the marker.

## Runtime Interpretation

**Decision**: Record both skip symbols rather than prematurely asserting that
removal is correct on all platforms.

**Rationale**: The pull request body asks whether the condition still applies;
detection should preserve the evidence and scope without making a runtime claim
that cannot be verified because tests are forbidden in this stage.

**Alternatives considered**: Rewriting or deleting the skips during planning was
rejected because project and test files are read-only.
