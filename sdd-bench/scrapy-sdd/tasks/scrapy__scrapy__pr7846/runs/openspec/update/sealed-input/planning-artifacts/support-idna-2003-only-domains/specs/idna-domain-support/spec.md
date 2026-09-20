## ADDED Requirements

### Requirement: Accept IDNA-2003-only hostnames

Scrapy SHALL allow a hostname that is accepted by Python's IDNA-2003 codec but rejected by Twisted's IDNA-2008 helper to be encoded for Twisted-backed network operations.

#### Scenario: Encode a legacy internationalized hostname

- **WHEN** Scrapy passes an IDNA-2003-only hostname to a Twisted IDNA encoding helper
- **THEN** the hostname SHALL be converted to its ASCII-compatible IDNA-2003 form instead of raising the IDNA-2008 error

#### Scenario: Preserve modern IDNA behavior

- **WHEN** a hostname is accepted by the IDNA-2008 helper
- **THEN** Scrapy SHALL preserve the helper's existing encoding result

### Requirement: Decode matching IDNA hostnames

Scrapy SHALL decode IDNA-encoded hostnames when the IDNA-2008 helper cannot decode them but Python's IDNA-2003 codec can.

#### Scenario: Decode a legacy encoded hostname

- **WHEN** Twisted receives ASCII-compatible bytes that are valid under IDNA-2003 but rejected by IDNA-2008 decoding
- **THEN** Scrapy SHALL return the IDNA-2003 text representation
