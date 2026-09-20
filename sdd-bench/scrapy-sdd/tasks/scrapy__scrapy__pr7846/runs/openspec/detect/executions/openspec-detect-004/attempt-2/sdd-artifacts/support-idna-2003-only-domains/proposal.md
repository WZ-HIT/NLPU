## Why

Some hosts that are valid under IDNA-2003 are rejected by the IDNA-2008 implementation used by Twisted, so Scrapy cannot resolve or connect to them. Scrapy should retain support for these legacy-but-valid domains without requiring users to patch Twisted themselves.

## What Changes

- Make Scrapy's import path install compatibility wrappers around Twisted's IDNA helpers.
- Encode hostnames with Twisted's existing IDNA-2008 path first, then fall back to Python's IDNA-2003 codec when that path rejects a domain.
- Decode IDNA bytes through the corresponding compatibility path so DNS and TLS hostname handling agree.
- Keep the workaround isolated to Twisted integration points and document its temporary nature.

## Capabilities

### New Capabilities

- `idna-domain-support`: Accept and handle domains supported by IDNA-2003 but rejected by IDNA-2008 in Twisted-backed networking.

### Modified Capabilities

None.

## Impact

Affected code is Scrapy's package import path and Twisted integration. The change affects hostname encoding for DNS resolution and TLS hostname verification, plus any tests exercising URL, resolver, or downloader behavior with internationalized domains.
