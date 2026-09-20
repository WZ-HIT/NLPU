# Research: Support IDNA-2003-only domains

## Decision: Patch Twisted conversion at Scrapy import time

**Rationale**: Twisted's resolver, endpoint, and TLS paths import and call its
IDNA helper functions internally. Scrapy can restore acceptance of
IDNA-2003-only hostnames without changing every call site by replacing those
helpers once, while the process still uses the current Twisted conversion for
valid names.

**Alternatives considered**:

- Require users to install or configure another resolver: rejected because the
  failure occurs before resolver selection and affects normal requests.
- Prefix every hostname manually in each downloader path: rejected because it
  duplicates logic and misses TLS/resolver consumers.
- Wait only for an upstream Twisted fix: rejected for this feature because the
  reported Scrapy behavior remains broken.

## Decision: Prefer existing conversion and fall back to the legacy codec

**Rationale**: A fallback preserves the current behavior for valid IDNA-2008
names and uses Python's built-in IDNA-2003 codec only when the preferred
conversion rejects a name that the legacy codec can represent. Invalid names
still raise an error when neither conversion succeeds.

**Alternatives considered**:

- Always use the built-in codec: rejected because it changes mappings for
  modern domains such as sharp-s names.
- Always use the `idna` package: rejected because it is the source of the
  IDNA-2003-only rejection.
- Guess an ASCII replacement for failures: rejected because resolving a
  different hostname would be unsafe.

## Decision: Verify at helper and consumer boundaries

**Rationale**: Unit-level checks pin the encoding behavior, while resolver,
request, TLS, and crawl tests prove the patched helpers are actually used by
real Scrapy paths.

**Alternatives considered**:

- Unit tests only: rejected because import-time timing or stale references
  could bypass the patch in real consumers.
