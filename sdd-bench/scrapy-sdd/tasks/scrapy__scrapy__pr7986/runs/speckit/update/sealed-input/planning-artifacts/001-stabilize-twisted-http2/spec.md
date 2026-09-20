# Feature Specification: Stabilize and Privatize the Twisted HTTP/2 Handler

**Feature Branch**: `001-stabilize-twisted-http2`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Repository `scrapy/scrapy`, PR `7986`: "Stop marking the Twisted-based HTTP/2 download handler as experimental, and privatize its API"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Use the handler without an experimental warning (Priority: P1)

As a Scrapy user, I can configure the Twisted-based HTTP/2 download handler without documentation presenting it as experimental or not recommended for production.

**Why this priority**: The handler is being promoted to a supported built-in option, which is the primary user-visible outcome.

**Independent Test**: Configure the handler for HTTPS downloads, perform an HTTP/2 request, and confirm the documented configuration remains valid without any experimental warning.

**Acceptance Scenarios**:

1. **Given** the Twisted HTTP/2 extra is installed, **When** the handler is selected through `DOWNLOAD_HANDLERS`, **Then** HTTPS requests use HTTP/2 successfully.
2. **Given** a user reads the download-handler documentation, **When** they review the Twisted HTTP/2 handler, **Then** it is not described as experimental or unsuitable for production.

---

### User Story 2 - Rely only on the supported handler interface (Priority: P2)

As a Scrapy maintainer, I can rename internal HTTP/2 implementation classes as private without changing the supported way users select and use the download handler.

**Why this priority**: Privatizing internals reduces the supported API surface while preserving the documented handler contract.

**Independent Test**: Import and exercise the download handler through its documented path while confirming internal implementation symbols are private and no supported public contract is broken.

**Acceptance Scenarios**:

1. **Given** the supported handler path, **When** Scrapy loads it from `DOWNLOAD_HANDLERS`, **Then** the handler still initializes and downloads requests.
2. **Given** internal HTTP/2 classes formerly exposed by implementation modules, **When** the implementation is inspected, **Then** those classes use private names and are not documented as supported API.

### Edge Cases

- Importing the internal implementation without the Twisted HTTP/2 extra must continue to remain unsupported and isolated.
- The reactor-disabled configuration must still reject the Twisted handler with the existing configuration error.
- Documentation references to the handler and its internal helpers must not point at removed public symbols.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Twisted-based HTTP/2 download handler MUST retain its supported handler class and configuration path.
- **FR-002**: Documentation MUST stop labeling the handler as experimental or unsuitable for production, while retaining its operational limitations.
- **FR-003**: Internal classes and helpers in the Twisted HTTP/2 implementation MUST use private names.
- **FR-004**: The download handler MUST preserve HTTP/2 request behavior, lazy initialization, cleanup, and reactor requirements.
- **FR-005**: Existing internal imports and references MUST be updated consistently so the package remains importable and type-checkable.
- **FR-006**: The HTTPX-based handler's separate experimental status MUST remain unchanged.

### Key Entities

- **Twisted HTTP/2 download handler**: The supported downloader component configured for HTTPS requests.
- **Internal HTTP/2 implementation**: Connection, protocol, stream, agent, factory, pool, and exception classes used only to implement the handler.
- **Download-handler documentation**: The user-facing contract describing availability, limitations, and configuration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The documented Twisted HTTP/2 configuration completes an HTTP/2 request successfully.
- **SC-002**: No experimental warning is emitted by the Twisted HTTP/2 handler.
- **SC-003**: All formerly public implementation class names identified by the change are absent from the supported namespace, with zero stale imports.
- **SC-004**: Existing HTTP/2 behavior tests continue to pass without changing user-facing handler configuration.

## Assumptions

- `H2DownloadHandler` remains the supported handler class because it is explicitly documented and configured by path.
- Classes in `scrapy.core.http2` that are imported only by implementation code are considered private.
- Historical release notes remain historical and are not rewritten.
