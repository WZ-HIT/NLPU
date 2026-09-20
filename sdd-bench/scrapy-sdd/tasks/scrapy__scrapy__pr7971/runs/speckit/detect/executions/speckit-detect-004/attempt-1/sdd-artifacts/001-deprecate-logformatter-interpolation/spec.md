# Feature Specification: Deprecate Log Formatter Message Interpolation With the Returned Dict

**Feature Branch**: `001-deprecate-logformatter-interpolation`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "scrapy/scrapy PR 7971: Deprecate interpolating log formatter messages with the returned dict. Alleviates the backward incompatibility of #7936."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Legacy custom log formatters keep working with a warning (Priority: P1)

A project that has a custom log formatter written against the pre-#7936 contract
returns a message whose placeholders are meant to be filled from the formatter
result dictionary itself, without supplying a separate `args` value. After this
change the project still sees the same log line, but also receives a deprecation
warning telling the maintainer to add an explicit `args` value.

**Why this priority**: This is the backward-compatibility fix that the pull
request exists to deliver; without it custom formatters break on upgrade.

**Independent Test**: Feed the adapter a formatter result that omits `args` and
whose message contains a placeholder that exists as a key of the returned
dictionary. Confirm the emitted log record contains the interpolated value and
that a deprecation warning is raised.

**Acceptance Scenarios**:

1. **Given** a formatter result with `level`, `msg`, and no `args`, **When** the
   message is logged, **Then** any placeholder matching a key of the returned
   dictionary is replaced by that value.
2. **Given** the same legacy result, **When** it is adapted for logging, **Then**
   a deprecation warning identifies the reliance on dict interpolation and
   recommends supplying `args`.
3. **Given** a formatter result that supplies `args` explicitly, **When** it is
   adapted, **Then** no deprecation warning is emitted.

---

### User Story 2 - Explicit `args` remains the supported contract (Priority: P2)

A project using the current documented contract returns `level`, `msg`, and an
explicit `args` mapping or tuple. The adapter continues to hand those values to
the standard logging call so that interpolation happens exactly once.

**Why this priority**: The deprecation must not change or double-apply
interpolation for formatters that already migrated.

**Independent Test**: Adapt results with mapping args and with tuple args and
confirm the produced log record text and the absence of warnings.

**Acceptance Scenarios**:

1. **Given** `msg="%(pct)d%% done"` and `args={"pct": 90}`, **When** logged,
   **Then** the record text is `90% done`.
2. **Given** `msg="%d%% done"` and `args=(90,)`, **When** logged, **Then** the
   record text is `90% done`.
3. **Given** empty or missing `args` on a message with no placeholders, **When**
   logged, **Then** the message is emitted unchanged and no warning is raised.

---

### Edge Cases

- A legacy message without placeholders must not be reformatted or broken by
  treating the returned dictionary as a mapping argument.
- A message containing a literal percent sign (for example `90% done`) must not
  raise a formatting error when the returned dictionary is used as the mapping.
- A result dictionary that omits `args` but whose message references a key that
  is absent must fail with the standard formatting error rather than silently
  producing a partially formatted message.
- Results that return `None` (intentionally suppressed messages) must continue to
  be skipped by callers and never reach the adapter.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When a formatter result omits `args` and its message is to be
  interpolated using the returned dictionary, the system MUST emit a deprecation
  warning instead of failing.
- **FR-002**: The system MUST preserve the rendered log text for legacy results
  that rely on dictionary interpolation during the deprecation period.
- **FR-003**: The system MUST continue to support explicit mapping `args` and
  tuple `args` without emitting a deprecation warning.
- **FR-004**: The system MUST fall back to an empty message and default level
  exactly as the current adapter does, so unrelated malformed results keep their
  present behavior.
- **FR-005**: The deprecation warning MUST be actionable, naming the deprecated
  dict-interpolation behavior and the migration to an explicit `args` value.
- **FR-006**: The change MUST NOT alter the `LogFormatter` methods' returned
  values; only the adaptation of those values for logging changes.

### Key Entities

- **Log formatter result**: The dictionary returned by a `LogFormatter` method,
  containing `level`, `msg`, and optionally `args`.
- **Deprecation warning**: The user-visible signal that dict-based interpolation
  of the message will be removed in a future release.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of existing adapter tests for explicit mapping and tuple args
  continue to produce identical log text.
- **SC-002**: A legacy result that relies on dict interpolation logs the same
  text as before the change and raises exactly one deprecation warning.
- **SC-003**: Results that omit `args` and contain no placeholders produce no
  warning and no text change.
- **SC-004**: No caller in the crawl pipeline needs modification, so suppressed
  (`None`) results remain skipped in 100% of existing suppression tests.

## Assumptions

- The legacy behavior being deprecated is the implicit use of the returned
  dictionary as the interpolation mapping when `args` is absent.
- The project's existing deprecation warning class and warning test conventions
  are reused rather than introducing a new warning type.
- Removing the legacy behavior is out of scope; this release only warns.
- Documentation and release notes may mention the deprecation but are not
  required for the behavior to be correct.
