# Feature Specification: Merge LxmlLinkExtractor Test Classes

**Feature Branch**: `8002-merge-linkextractor-tests`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Pull request 8002: "Merge LxmlLinkExtractor test classes. There is only one link extractor class now."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Maintain one discoverable link extractor test suite (Priority: P1)

As a Scrapy maintainer, I want the link extractor behavior tests expressed in one discoverable test class so that the test suite reflects the single public link extractor implementation.

**Why this priority**: The refactor removes obsolete test-suite indirection and reduces maintenance cost without changing user-visible behavior.

**Independent Test**: Inspect and run the link extractor test module. The tests that formerly lived in the hidden base class and the concrete LxmlLinkExtractor class are discoverable through one class, while every existing behavior assertion remains present.

**Acceptance Scenarios**:

1. **Given** the current hidden test base and concrete LxmlLinkExtractor test class, **When** the test classes are consolidated, **Then** one discoverable class contains the shared extraction tests and the LxmlLinkExtractor-specific tests.
2. **Given** the existing test inventory, **When** the consolidation is complete, **Then** all existing LxmlLinkExtractor behavior tests and their assertions remain represented without introducing a dummy base class.
3. **Given** the LxmlParserLinkExtractor-specific tests, **When** the consolidation is complete, **Then** those tests remain separate and unchanged in behavior.

### Edge Cases

- Class-level extractor selection and shared response setup must continue to apply to every consolidated test.
- Conditional skipping for older w3lib versions must remain attached to the bad-link test.
- Test collection must not expose a class named as a pytest test class when it exists only as a hiding mechanism.
- The internal LxmlParserLinkExtractor tests are outside the public extractor-class consolidation and must not be accidentally dropped.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The link extractor test module MUST expose one discoverable test class for LxmlLinkExtractor behavior.
- **FR-002**: The consolidated class MUST include the existing shared extraction, filtering, restriction, encoding, nofollow, canonicalization, and aggregation tests.
- **FR-003**: The consolidated class MUST include the existing LxmlLinkExtractor-specific tests.
- **FR-004**: The consolidation MUST preserve all existing test methods, assertions, marks, fixtures, and test names unless a rename is required solely by the class merge.
- **FR-005**: The test module MUST no longer require a placeholder base class whose only purpose is to hide inherited tests from pytest.
- **FR-006**: LxmlParserLinkExtractor tests MUST remain independently identifiable and behaviorally unchanged.
- **FR-007**: The change MUST NOT alter production behavior or require production-code changes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The link extractor module has exactly one discoverable test class dedicated to LxmlLinkExtractor behavior.
- **SC-002**: All 38 pre-existing LxmlLinkExtractor test cases (32 shared plus 6 concrete) remain represented.
- **SC-003**: Zero tests are lost, silently skipped, or made undiscoverable by the class consolidation.
- **SC-004**: The 3 LxmlParserLinkExtractor tests retain their existing names and behavior.
- **SC-005**: The targeted link extractor test file completes successfully in the repository's normal pytest environment.

## Assumptions

- The pull request is limited to reorganizing tests and does not change the public LinkExtractor API.
- `LxmlLinkExtractor` remains the only public link extractor covered by the shared behavior suite.
- Existing pytest discovery and test dependencies remain available.
- Test execution is a later implementation-phase validation step; planning does not run it.
