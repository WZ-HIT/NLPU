# Feature Specification: Support IDNA-2003-only domains

**Feature Branch**: `support-idna-2003-domains`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Support IDNA-2003-only domains by monkey-patching Twisted IDNA helpers.

## User Scenarios & Testing

### User Story 1 - Reach a legacy internationalized hostname (Priority: P1)

A spider author submits a request whose hostname can be represented by IDNA-2003
but rejected by an IDNA-2008-only validation path. Scrapy must preserve the
hostname conversion and resolve or connect to the expected ASCII hostname.

**Why this priority**: This is the regression that prevents affected domains
from being crawled at all.

**Independent Test**: Construct a request for an IDNA-2003-only domain and
verify that hostname encoding and resolution do not raise a Unicode/IDNA error
and use the same ASCII hostname throughout.

**Acceptance Scenarios**:

1. **Given** an IDNA-2003-only Unicode hostname, **when** Twisted performs
   hostname resolution, **then** it receives the corresponding ASCII hostname.
2. **Given** the equivalent already-punycoded hostname, **when** Twisted
   converts it for DNS or TLS, **then** conversion succeeds without changing
   the intended host.

### User Story 2 - Preserve existing IDNA behavior (Priority: P2)

Existing valid ASCII, IDNA-2003, and IDNA-2008 hostnames must continue to
resolve and connect normally.

**Why this priority**: The compatibility shim must not regress ordinary or
modern internationalized domains.

**Independent Test**: Exercise representative ASCII, IDNA-2003, and IDNA-2008
names through the affected helper and resolver paths.

**Acceptance Scenarios**:

1. **Given** a normal ASCII hostname, **when** it is converted, **then** the
   result is unchanged.
2. **Given** a valid modern internationalized hostname, **when** it is
   converted, **then** its established punycode form is preserved.

### Edge Cases

- Names already in ASCII punycode form.
- Invalid or overlong labels: the original conversion failure must remain
  visible rather than being silently changed into a different host.
- Both resolver helper paths and TLS hostname verification must agree on the
  converted hostname.

## Requirements

### Functional Requirements

- **FR-001**: Scrapy MUST accept hostnames supported by IDNA-2003 but rejected
  by IDNA-2008-only validation.
- **FR-002**: The compatibility behavior MUST apply to Twisted hostname
  conversion used by resolution and TLS.
- **FR-003**: ASCII and otherwise valid hostnames MUST keep their existing
  conversion results.
- **FR-004**: Invalid hostnames MUST still fail rather than being resolved under
  an unintended fallback name.
- **FR-005**: The behavior MUST be activated consistently when Scrapy is
  imported, without requiring per-request configuration.

### Key Entities

- **Hostname**: A user-supplied or already-punycoded network name that may
  contain internationalized characters.
- **ASCII hostname**: The encoded form passed to the resolver or TLS layer.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Requests to IDNA-2003-only hostnames complete hostname conversion
  instead of failing before DNS resolution.
- **SC-002**: Existing resolver, request, and downloader tests retain their
  expected behavior.
- **SC-003**: Automated coverage includes at least one IDNA-2003-only name and
  one ordinary ASCII name through the compatibility path.

## Assumptions

- Scrapy remains responsible for its compatibility behavior until the
  underlying Twisted behavior is changed upstream.
- The conversion must not alter request URLs or user-visible hostnames beyond
  the ASCII form already produced during request normalization.
- No new user-facing setting is required.
