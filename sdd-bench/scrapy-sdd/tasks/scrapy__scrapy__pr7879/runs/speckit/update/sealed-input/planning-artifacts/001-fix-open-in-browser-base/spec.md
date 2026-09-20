# Feature Specification: Fix open_in_browser base insertion without a head

**Feature Branch**: `001-fix-open-in-browser-base`

**Created**: 2026-09-20

**Status**: Draft

**Input**: PR #7879: Fix `open_in_browser` not adding a base tag without a head element.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preview HTML that has no head element (Priority: P1)

A developer opens an HTML response in a browser for debugging. The response has no `<head>` element, so relative resources cannot be resolved unless preview preparation supplies an effective base URL.

**Why this priority**: This is the reported failure and the main value of the fix.

**Independent Test**: Open an HTML response whose body has no real `<head>` and no effective `<base>`, then confirm the browser output contains exactly one base element using the response URL.

**Acceptance Scenarios**:

1. **Given** an HTML response with content but no head or base element, **When** it is opened in a browser, **Then** the preview contains one effective base element with the response URL.
2. **Given** an HTML response with a head element, **When** it is opened in a browser, **Then** the base element is placed inside that head element as before.
3. **Given** an HTML response with an existing effective base element, **When** it is opened in a browser, **Then** no second base element is added.

---

### User Story 2 - Preserve preview content and behavior (Priority: P2)

A developer relies on browser previews preserving the original document and on comments not being mistaken for markup. Existing behavior for text responses and malformed HTML must remain stable.

**Why this priority**: The fix must not make previews lose comments, duplicate bases, or introduce a performance regression.

**Independent Test**: Reopen representative HTML bodies with comments, commented-out heads or bases, existing bases, malformed head-like text, and text responses; verify the output remains correct.

**Acceptance Scenarios**:

1. **Given** a document containing comments, **When** it is opened, **Then** the comments remain in the preview.
2. **Given** a base or head marker only inside a comment, **When** the document is opened, **Then** the comment does not prevent insertion of the intended base.
3. **Given** a non-HTML text response, **When** it is opened, **Then** it is still written as text without base insertion.

### Edge Cases

- The body starts directly with content and has no `<html>` or `<head>`.
- The document contains uppercase or attributed head markup.
- A comment contains `<head>`, `<base>`, or a partial head-like token.
- Malformed input contains repeated `<head` text without a closing `>`.
- A real base element already exists and must not be duplicated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: HTML previews MUST receive an effective base URL when the document has no head element and no effective base element.
- **FR-002**: When a real head element exists, the base element MUST continue to be inserted inside it without replacing the head tag.
- **FR-003**: An existing effective base element MUST prevent duplicate insertion.
- **FR-004**: Head or base text inside comments MUST NOT count as a real head or base element.
- **FR-005**: Existing comments and document content MUST be preserved except for the required base insertion.
- **FR-006**: Plain text responses and unsupported response types MUST retain their existing behavior.
- **FR-007**: Preview preparation MUST remain safe for malformed, large, or adversarial HTML inputs.

### Key Entities

- **HTML response**: The document being prepared for browser preview, including its URL and body.
- **Head element**: The real document section where a base element is normally inserted.
- **Base element**: The effective URL used by the browser to resolve relative resources.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of tested HTML cases without a head or base element produce exactly one effective base element.
- **SC-002**: 100% of tested cases with an existing effective base remain free of duplicate base elements.
- **SC-003**: 100% of tested existing-comment cases retain their comments and 100% of plain text cases retain text behavior.
- **SC-004**: All existing browser-preview checks that are run in the implementation phase pass.
- **SC-005**: Malformed and adversarial preview inputs remain within the existing performance expectation.

## Assumptions

- The base URL is the response URL.
- The public function signature and return behavior do not change.
- Browser preview remains an HTML-specific convenience and does not become a normal scraping path.
- Existing comment handling and ReDoS protections are retained.
