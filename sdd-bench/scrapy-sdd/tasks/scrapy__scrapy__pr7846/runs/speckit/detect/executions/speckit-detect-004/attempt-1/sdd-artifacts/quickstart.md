# Quickstart Validation: Support IDNA-2003-only domains

Do not execute these commands during the planning phase. They are the intended
validation procedure after implementation.

## Prerequisites

- The repository test dependencies are installed.
- A representative IDNA-2003-only hostname is used, such as an IDNA-2003
  punycode name rejected by the IDNA-2008-only conversion.

## Focused checks

Run the focused URL, resolver, request, and TLS test files identified in
`detection-draft.json` once implementation is available. Confirm that:

1. The compatibility helper returns an ASCII-only hostname for the legacy-only
   input.
2. Existing ASCII and modern internationalized hostnames still return their
   previous values.
3. A request using the legacy-only hostname reaches resolution with the
   expected ASCII hostname.
4. Invalid hostnames continue to fail.

## Expected outcome

No Unicode/IDNA conversion exception occurs for the supported legacy-only
hostname, and existing resolver and downloader behavior remains unchanged.
