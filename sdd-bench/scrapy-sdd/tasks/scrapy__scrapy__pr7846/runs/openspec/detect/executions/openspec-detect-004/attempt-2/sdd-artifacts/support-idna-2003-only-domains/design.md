## Context

Twisted 26.4.0 routes hostname conversion through `twisted.internet._idna._idnaBytes` and `_idnaText`. Those helpers prefer the `idna` package, which implements IDNA-2008 and can reject names that Python's built-in `encodings.idna` codec accepts under IDNA-2003. Scrapy depends on Twisted for DNS and TLS, so a compatibility adjustment must be installed before those imported helper references are used.

## Goals / Non-Goals

### Goals

- Preserve existing IDNA-2008 behavior whenever it succeeds.
- Fall back to `str.encode("idna")` and `bytes.decode("idna")` for legacy-only names.
- Cover both helper call paths used by Twisted DNS/endpoints and TLS verification.

### Non-Goals

- Reimplement IDNA or change URL parsing semantics outside Twisted hostname conversion.
- Make IDNA-2003 the preferred behavior for modern domains.
- Vendor or replace Twisted.

## Decisions

### Compatibility wrappers

Define Scrapy-side wrappers with the same call signatures as Twisted's `_idnaBytes` and `_idnaText`. Each wrapper calls the original helper first and catches only the IDNA failure relevant to that helper before trying the standard-library codec. Unexpected exceptions remain visible.

### Patch timing and scope

Install the wrappers during Scrapy package initialization so they are available before normal crawler startup. Patch both the defining module and modules that imported the helpers by value, because Twisted currently uses direct imports in DNS, endpoint, resolver, and TLS code. Preserve references to the original callables to avoid recursive wrapping on repeated imports.

### Verification

Use focused tests that compare a modern hostname (unchanged result) with an IDNA-2003-only hostname (fallback result), then exercise the relevant downloader or TLS surface without relying on public DNS.

## Risks / Trade-offs

- Monkey-patching private Twisted APIs is version-sensitive; narrow exception handling and import-time tests reduce accidental behavior changes.
- IDNA-2003 and IDNA-2008 can produce different ASCII forms for a name; the fallback intentionally favors compatibility only when IDNA-2008 has already failed.
- Twisted may change private helper names or import structure in future releases, so the patch must be easy to remove.
