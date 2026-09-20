## Context

`H2DownloadHandler` is registered through `DOWNLOAD_HANDLERS` and currently
lives in `scrapy.core.downloader.handlers.http2`. Its implementation relies on
`scrapy.core.http2.agent`, `protocol`, and `stream`. The handler is already
tested through the shared HTTPS download-handler suites and has dedicated
HTTP/2 protocol tests. The previous API-privatization work for HTTP/1.1 kept the
public handler classes in their existing modules while prefixing internal
helpers with underscores; the non-experimental `HttpxDownloadHandler` instead
lives in `_httpx.py`. This change follows the latter precedent for the
Twisted-based HTTP/2 implementation.

## Goals

- Present the Twisted HTTP/2 handler as supported rather than experimental.
- Make the implementation import path visibly private.
- Preserve the handler's runtime behavior and configuration surface.
- Keep documentation and tests aligned with the new path.

## Non-Goals

- Implementing proxy support or changing HTTP/2 protocol behavior.
- Changing `DOWNLOAD_HANDLERS` semantics or settings.
- Rewriting historical release notes to use the new private path.
- Redesigning the download-handler interface.

## Decisions

### Private import path

Move `scrapy/core/downloader/handlers/http2.py` to `_http2.py` and move
`scrapy/core/http2/` to `scrapy/core/_http2/`. Update the documented
`DOWNLOAD_HANDLERS` string path, all current documentation links, production
imports, and test imports to those private paths. Do not add a compatibility
alias: the old handler API was explicitly experimental, and this PR is the
point at which its API contract is corrected.

The handler class remains `H2DownloadHandler`, matching
`_httpx.HttpxDownloadHandler`: the module path is private while the identifier
used in user configuration remains recognizable. Internally owned protocol,
stream, pool, and agent symbols remain in the private package and are not
documented as user-facing APIs.

### No runtime behavior changes

Retain the existing `BaseDownloadHandler` lifecycle, `H2ConnectionPool`,
timeouts, TLS context loading, bind-address normalization, and unsupported
plain-HTTP error. This keeps the change reviewable and avoids conflating API
cleanup with protocol fixes.

## Risks and Mitigations

- **Risk:** Users following the old documented path break immediately.
  **Mitigation:** Mark the change clearly as breaking, update current docs, and
  rely on the prior experimental warning as the compatibility contract.
- **Risk:** Internal imports or string-based patches retain stale module names.
  **Mitigation:** Search the repository for both `handlers.http2` and
  `scrapy.core.http2`, then update production imports and test patch targets.
- **Risk:** Documentation references in old release notes fail to resolve.
  **Mitigation:** Leave historical notes intact unless the documentation build's
  link policy requires a redirect/alias; do not rewrite historical records.

## Verification Strategy

- Inspect imports and `DOWNLOAD_HANDLERS` examples after the rename.
- Run the dedicated Twisted HTTP/2 handler tests and HTTP/2 protocol tests when
  the implementation stage permits test execution.
- Confirm no current documentation describes the handler as experimental and
  no current code imports the old path.

## Migration Plan

Update implementation imports first, then the documented handler path and
tests in the same change. There is no runtime data migration or deployment
step. Rollback is limited to reverting the path and documentation changes,
since request/response behavior is untouched.
