# Detect planning notes — PR 7846 (IDNA-2003-only domains)

Scope: planning-only detection for `scrapy/scrapy` PR 7846 ("Support
IDNA-2003-only domains by monkey-patching Twisted IDNA helpers") on base
commit `488a762d7173922190ea027e0fb6f6d9d3b59880`. No project code or tests
were modified, and no tests were run.

## Change under analysis

The pull request patches Twisted's IDNA helpers at Scrapy import time so
domains valid only under IDNA-2003 still resolve. In Twisted 26.4.0 the shared
helpers live in `twisted/internet/_idna.py` (`_idnaBytes`, `_idnaText`) and
prefer the PyPI `idna` package (IDNA-2008), using the stdlib `encodings.idna`
implementation only when that package is absent. References are imported by
value into `twisted.internet._resolver`, `twisted.internet.endpoints`, and
`twisted.internet._sslverify`.

Concrete failure: `"xn--n3h.net"` (Punycode for `☃.net`, an IDNA-2003-only
domain) is accepted by `"☃.net".encode("idna")` — the conversion
`w3lib.url.safe_url_string` uses when Scrapy builds `Request.url` — but
`idna.decode("xn--n3h.net")` raises `InvalidCodepoint`.
`HostnameEndpoint._parse` then marks the host invalid and the download fails.
The patch makes the helpers tolerate such names.

## Detection strategy

Candidate test files were selected by tracing every repository test that
reaches a patched helper:

1. Request URL normalization (w3lib `safe_url_string`, stdlib IDNA-2003).
2. Twisted host endpoint parsing (`_idnaText` / `_idnaBytes`).
3. Twisted resolver lookups (`_resolver`, `Caching*Resolver`).
4. TLS hostname verification (`_sslverify` -> `_hostnameBytes`).
5. Twisted-to-Scrapy exception mapping for lookup failures.

Symbols listed per candidate are the classes/functions in that file that sit on
one of those paths and are therefore the most likely places a regression or a
new IDNA-2003-only case would be observed.

## Expected verification shape

Integration coverage for a new IDNA-2003-only host would most likely be added
as a new base class in `tests/utils/bases/download_handlers_http.py` with
subclasses in the Twisted HTTP/1.1 and HTTP/2 handler test modules; unit-level
coverage would sit next to the resolver, TLS context factory, or request URL
normalization tests listed in the draft.

`detection-draft.json` in this directory is the machine-readable output of this
phase and contains only the `candidates` array.
