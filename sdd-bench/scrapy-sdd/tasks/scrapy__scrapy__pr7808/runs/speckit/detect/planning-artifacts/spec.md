# Feature Specification: Generalize Internal Component Construction

**Created**: 2026-09-20

**Status**: Draft

**Input**: Pull request `scrapy/scrapy#7808`, "Generalize the use of build_from_crawler() internally"

## User Scenarios & Testing

### User Story 1 - Construct optional components consistently (Priority: P1)

As a Scrapy component author, I can define either `from_crawler()` or only an
`__init__()` method, and the component is constructed consistently wherever
Scrapy creates it internally.

**Why this priority**: The public component contract is implemented by
`build_from_crawler()`, but several internal call sites still require
`from_crawler()` directly.

**Independent Test**: Configure an internal component class that has only an
`__init__()` constructor and verify that crawler startup constructs it.

**Acceptance Scenarios**:

1. **Given** a configurable component with only `__init__()`, **When** Scrapy
   creates it internally, **Then** it is initialized without requiring
   `from_crawler()`.
2. **Given** a component with `from_crawler()`, **When** Scrapy creates it,
   **Then** `from_crawler(crawler, *args, **kwargs)` remains the constructor
   used.
3. **Given** a constructor that returns `None`, **When** Scrapy creates the
   component, **Then** construction fails with the same `TypeError` provided by
   `build_from_crawler()`.

### Edge Cases

- Components with stateful class-level `from_crawler()` implementations must
  retain their existing behavior.
- Parser construction must forward parser-specific arguments and must not pass
  the crawler to an `__init__()` fallback.
- Deprecated code paths that construct a mail sender must preserve their
  warnings and runtime behavior.

## Requirements

### Functional Requirements

- **FR-001**: Internal construction of downloader, spider, and item-pipeline
  managers MUST use `build_from_crawler()`.
- **FR-002**: Internal construction of configurable log formatters and item
  processors MUST use `build_from_crawler()`.
- **FR-003**: Internal construction of extension managers, mail senders, and
  robots.txt parser implementations MUST use `build_from_crawler()`.
- **FR-004**: Existing `from_crawler()` and `__init__()` precedence, argument
  forwarding, and `None` validation MUST remain consistent with the public
  helper.
- **FR-005**: Existing spider creation semantics MUST remain compatible with
  the crawler lifecycle.

### Key Entities

- **Crawler component**: A class created during crawler setup using the
  component construction contract.
- **Constructor helper**: The shared utility that selects `from_crawler()` when
  available and otherwise invokes `__init__()`.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every identified internal direct `from_crawler()` constructor
  call is either converted to the shared helper or explicitly excluded with a
  lifecycle rationale.
- **SC-002**: Existing component tests pass without behavioral regression.
- **SC-003**: New targeted coverage demonstrates construction of at least one
  `__init__()`-only internal component.

## Assumptions

- The change is an internal consistency refactor and does not alter public
  APIs.
- `Crawler._create_spider()` may remain on `spidercls.from_crawler()` because
  spider creation has stricter lifecycle semantics.
- Candidate tests are existing repository test files; tests are not executed
  during this planning-only task.
