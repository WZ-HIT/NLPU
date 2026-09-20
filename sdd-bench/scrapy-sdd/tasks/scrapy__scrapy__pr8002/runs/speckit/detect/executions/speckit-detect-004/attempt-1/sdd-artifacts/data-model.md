# Phase 1 Data Model: Merge LxmlLinkExtractor Test Classes

This feature has no persisted or domain data. The model below describes the test-suite structure that the refactor changes.

## Test Suite Unit

**Name**: LxmlLinkExtractor test class

**Fields**:

- `extractor_cls`: the public extractor implementation under test
- `response`: shared HTML response fixture prepared for each test
- `test methods`: shared and extractor-specific behavior cases

**Validation rules**:

- Must be directly discoverable by pytest.
- Must contain all 32 shared behavior tests and 6 LxmlLinkExtractor-specific tests.
- Must not depend on a hidden base class for pytest discoverability.

## Shared Behavior Tests

**Represents**: Filtering, extraction, restriction, encoding, nofollow handling, canonicalization, pickling, and link aggregation behavior.

**Relationship**: Belongs to the single LxmlLinkExtractor test class after consolidation.

## LxmlLinkExtractor-Specific Tests

**Represents**: Canonicalization call count, text restriction, bad URL handling, and URL admission rules specific to the public extractor.

**Relationship**: Belongs to the same LxmlLinkExtractor test class after consolidation.

## LxmlParserLinkExtractor Tests

**Represents**: Tests for the internal parser extractor.

**Relationship**: Remains a separate test class; not merged into the public extractor suite.
