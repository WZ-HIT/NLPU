# Feature Specification: SSLKEYLOGFILE Support

**Feature Branch**: `001-sslkeylogfile-support`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "Add SSLKEYLOGFILE support (scrapy/scrapy#7948), resolving scrapy/scrapy#4368."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Capture TLS session keys for diagnosis (Priority: P1)

An operator diagnosing an HTTPS crawl can direct key material to a file and use it with a compatible traffic-analysis tool to decrypt captured TLS traffic.

**Why this priority**: This is the purpose of the change and the minimum useful outcome.

**Independent Test**: Configure a key-log destination, make an HTTPS request through each supported download handler, and confirm that the destination receives standard key-log records while the request still succeeds.

**Acceptance Scenarios**:

1. **Given** a valid key-log destination is configured, **When** an HTTPS request is downloaded, **Then** TLS key material is written in the standard NSS key-log format.
2. **Given** no key-log destination is configured, **When** an HTTPS request is downloaded, **Then** behavior and output remain unchanged.

---

### User Story 2 - Avoid credential leakage during normal crawls (Priority: P2)

A crawl owner can rely on key logging being inactive unless explicitly requested.

**Why this priority**: TLS key material weakens the confidentiality of captured traffic, so explicit opt-in is a security requirement.

**Independent Test**: Run an HTTPS request without enabling the feature and verify that no key-log file is created or populated.

**Acceptance Scenarios**:

1. **Given** no key-log destination is configured, **When** a crawl runs, **Then** Scrapy does not create or append to a key-log file.

---

### User Story 3 - Consistent HTTPS handler behavior (Priority: P2)

A user enabling key logging gets the same opt-in behavior regardless of which HTTPS download handler is active.

**Why this priority**: Handler-specific behavior would make diagnosis unreliable.

**Independent Test**: Exercise the same configuration against each built-in HTTPS-capable handler and compare the presence and format of generated records.

**Acceptance Scenarios**:

1. **Given** key logging is enabled, **When** HTTPS requests use the stdlib and Twisted-based handlers, **Then** each handler writes compatible key-log records.

### Edge Cases

- The configured parent directory does not exist or is not writable.
- The key-log file already exists and contains earlier records.
- Several connections emit key material during the same crawl.
- TLS 1.2 and TLS 1.3 negotiate successfully.
- The process has no permission to inspect or modify the destination.
- Key logging is requested but the installed TLS implementation cannot expose key material.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST keep TLS key logging disabled by default.
- **FR-002**: Users MUST be able to opt in to key logging for HTTPS connections without replacing the download handler.
- **FR-003**: The system MUST write records in the standard NSS `SSLKEYLOGFILE` text format when enabled.
- **FR-004**: The system MUST preserve existing request behavior when key logging is enabled.
- **FR-005**: The system MUST route key material from every built-in HTTPS-capable handler through the same opt-in configuration.
- **FR-006**: The system MUST document the configuration, security implications, and intended diagnostic use.
- **FR-007**: The system MUST fail predictably when the destination cannot be used.

### Key Entities

- **Key-log destination**: The user-selected file that receives TLS key material.
- **Key-log record**: A standard-format line containing connection secrets and client-random material.
- **HTTPS connection**: A TLS session whose generated keys can be recorded.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With opt-in enabled, 100% of successful built-in HTTPS handler test connections produce at least one valid key-log record.
- **SC-002**: With opt-in disabled, 0 key-log files or records are created by Scrapy.
- **SC-003**: Existing HTTPS request success and response-body assertions remain unchanged when the feature is enabled.
- **SC-004**: The documentation lets a user enable and locate the key-log output without reading source code.

## Assumptions

- The existing operating-system `SSLKEYLOGFILE` convention is the user-facing interface unless project review selects a Scrapy setting.
- Only built-in HTTPS-capable handlers are in scope; third-party handlers may need to adopt the same utility.
- Captured key material is handled by the user and is not logged through Scrapy's normal logging system.
- The destination file is append-oriented so multiple connections can contribute records.
