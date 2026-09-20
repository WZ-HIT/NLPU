## Why

Scrapy cannot currently export TLS session secrets for protocol analysis. The standard `SSLKEYLOGFILE` environment variable lets users capture keys without modifying crawler code or weakening TLS verification.

## What Changes

- Read `SSLKEYLOGFILE` when the built-in Twisted TLS context factories create client contexts.
- Write negotiated TLS secrets to the configured file in the NSS key-log format.
- Keep behavior unchanged when the variable is unset or empty.
- Preserve existing TLS verification, cipher, protocol-version, and logging behavior.

## Capabilities

### New Capabilities

- `tls-key-logging`: Optional TLS session-key export controlled by `SSLKEYLOGFILE`.

### Modified Capabilities

None.

## Impact

Affects the built-in HTTP/1.1 and HTTP/2 download handlers, `scrapy.core.downloader.contextfactory`, TLS documentation, and downloader tests.
