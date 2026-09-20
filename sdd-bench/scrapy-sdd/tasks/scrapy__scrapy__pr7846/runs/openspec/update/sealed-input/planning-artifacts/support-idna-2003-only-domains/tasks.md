## 1. Implement compatibility wrappers

- [ ] 1.1 Add a focused Scrapy module that wraps Twisted's `_idnaBytes` and `_idnaText` helpers with IDNA-2008-first, IDNA-2003-fallback behavior.
- [ ] 1.2 Patch the defining Twisted module and by-value imports used by DNS, endpoint, resolver, and TLS code, preserving original callables and avoiding repeated wrapping.
- [ ] 1.3 Invoke the compatibility installation from the Scrapy package import path.

## 2. Add regression coverage

- [ ] 2.1 Add unit tests proving modern IDNA names retain the original result and IDNA-2003-only names use the fallback.
- [ ] 2.2 Add focused DNS/TLS integration coverage for a hostname represented differently by IDNA-2003 and IDNA-2008.

## 3. Validate and document

- [ ] 3.1 Run the focused URL, resolver, SSL, and downloader-handler tests.
- [ ] 3.2 Run the relevant static checks and confirm no unrelated behavior changes.
- [ ] 3.3 Document the compatibility workaround and its removal condition once Twisted exposes supported IDNA-2003 handling.
