# Quickstart Validation: SSLKEYLOGFILE Support

## Prerequisites

- A Scrapy checkout with the feature implemented.
- An HTTPS endpoint compatible with the repository's test mock servers.
- A compatible traffic-analysis tool for optional manual verification.

## Validation Scenarios

1. Start with no key-log destination configured. Run an HTTPS request and confirm that no new key-log file or records appear.
2. Configure a key-log destination in a temporary directory. Run an HTTPS request through the Twisted HTTP/1.1 handler and confirm the response succeeds and the file contains at least one standard record.
3. Repeat step 2 with the Twisted HTTP/2 and HTTPX handlers. Confirm each handler produces compatible records.
4. Run an HTTPS request with existing records already in the destination. Confirm prior records remain and new records append.
5. In an isolated environment, point the destination at an unusable path and confirm the failure is understandable.
6. Run the focused SSL utility, context-factory, and HTTPS handler tests identified in `detection-draft.json`.

## Expected Outcomes

- Disabled behavior is unchanged and produces no secrets.
- Enabled behavior produces file-based NSS-format records for every built-in HTTPS handler.
- Existing TLS and HTTP behavior remains intact.

## Security Note

Key-log output can decrypt captured TLS sessions. Delete it after diagnosis and never attach it to public reports.
