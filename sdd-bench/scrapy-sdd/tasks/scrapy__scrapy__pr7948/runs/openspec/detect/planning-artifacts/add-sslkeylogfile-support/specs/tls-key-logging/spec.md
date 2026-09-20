## Purpose

Allows operators to capture TLS session keys for debugging encrypted Scrapy traffic when explicitly enabled.

## ADDED Requirements

### Requirement: SSLKEYLOGFILE enables TLS key logging

When the `SSLKEYLOGFILE` environment variable is set to a non-empty value, Scrapy SHALL configure TLS client contexts used by the built-in HTTP download handlers to append negotiated session secrets to that file in the NSS key-log format.

#### Scenario: HTTPS request with key logging enabled

- **WHEN** `SSLKEYLOGFILE` names a writable file and Scrapy makes an HTTPS request through a built-in download handler
- **THEN** the file contains key-log records for the TLS session

#### Scenario: Key logging disabled

- **WHEN** `SSLKEYLOGFILE` is unset or empty
- **THEN** Scrapy creates no key-log file and HTTPS requests behave as before
