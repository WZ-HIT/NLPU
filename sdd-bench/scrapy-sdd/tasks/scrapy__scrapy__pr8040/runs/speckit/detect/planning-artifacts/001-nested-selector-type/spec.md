# Feature Specification: Nested Selector Type Inference

**Feature Branch**: `001-nested-selector-type`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "Let parsel determine the type of nested selectors"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preserve Parsel Inference for Nested Results (Priority: P1)

As a Scrapy user, I want selectors produced from an existing parsed root to retain the representation inferred by parsel, so nested JSON, HTML, XML, and text results remain usable with their appropriate selection methods.

**Why this priority**: This is the complete user-visible behavior requested by the PR and prevents Scrapy from overriding parsel's inference for nested selectors.

**Independent Test**: Create a selector from a root value without an explicit type, inspect its inferred type, and continue selecting from it. A nested JSON scalar must be usable as JSON rather than being treated as HTML.

**Acceptance Scenarios**:

1. **Given** a selector constructed from an existing root and no explicit type, **When** the root is a JSON scalar, **Then** parsel infers `json` and the resulting type is `json`.
2. **Given** a selector constructed from an existing root and no explicit type, **When** the root is an HTML or XML element, **Then** the element representation determines the corresponding non-JSON type.
3. **Given** a selector with an explicit type, **When** it is constructed, **Then** the explicit type is preserved.

---

### User Story 2 - Preserve Response-Based Defaults (Priority: P2)

As a Scrapy user, I want selectors created directly from response objects to continue using Scrapy's response-class defaults, so existing HTML, XML, JSON, and other response behavior does not regress.

**Why this priority**: The inference change must be limited to nested or root-based selectors and must not alter top-level response handling.

**Independent Test**: Construct selectors from `HtmlResponse`, `XmlResponse`, `JsonResponse`, and the general text response type, then verify their existing inferred types.

**Acceptance Scenarios**:

1. **Given** an HTML, XML, or JSON response, **When** a selector is created without an explicit type, **Then** the response class still determines the selector type.
2. **Given** a response that is not one of the recognized response subclasses, **When** a selector is created, **Then** parsel continues to infer the type from the response body.

### Edge Cases

- An explicitly supplied selector type must take precedence over response and root inference.
- A root passed by parsel as part of a nested selector must not be mistaken for a top-level response-less selector.
- Existing text and JSON selection behavior must remain compatible with the supported parsel version.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Scrapy MUST avoid assigning a concrete selector type when the caller supplies an existing root and does not explicitly request a type.
- **FR-002**: In that root-based case, Scrapy MUST delegate type inference for the root to parsel.
- **FR-003**: Scrapy MUST continue assigning response-specific defaults when a selector is created from a supported Scrapy response and no explicit type is supplied.
- **FR-004**: An explicitly supplied selector type MUST continue to override inference.
- **FR-005**: Nested JSON results and nested structured values MUST be able to use JSON selection methods according to parsel's behavior.
- **FR-006**: The behavior MUST remain compatible with the project's supported parsel versions.

### Key Entities

- **Selector input**: A response, text, body, or existing parsed root supplied when constructing a selector.
- **Root sentinel**: The internal marker that distinguishes an omitted root from a supplied root.
- **Inferred selector type**: One of the supported HTML, XML, JSON, or text representations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All existing selector tests that assert response-based type defaults continue to pass.
- **SC-002**: A selector created from a nested JSON scalar without an explicit type reports the type inferred by parsel instead of HTML.
- **SC-003**: Existing explicit-type selector behavior is unchanged.
- **SC-004**: No unrelated selector, response, or extraction behavior changes.

## Assumptions

- Parsel's public constructor already provides the intended inference behavior when Scrapy does not override the type.
- The existing internal "not set" root marker can be used to distinguish omitted roots from roots supplied by parsel during nested selection.
- Test execution is deferred; this planning stage only identifies the relevant test candidate.
