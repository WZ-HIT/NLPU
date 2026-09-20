---
description: "Task list for ISO 8601 date/time serialization in ScrapyJSONEncoder"
---

# Tasks: ISO 8601 Date and Time Serialization in ScrapyJSONEncoder

**Input**: Design documents from `/specs/001-json-iso8601-datetimes/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included below because the existing suite asserts the previous text format for
temporal values, so those expectations must change with the feature. These tasks are
descriptive only and are not executed in this Detect planning stage.

**Organization**: Tasks are grouped by user story from spec.md.

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 [P] Inventory every consumer of the JSON encoder and confirm the blast radius against scrapy/utils/serialize.py
- [ ] T002 [P] Record the current temporal output format to compare against after the change in scrapy/utils/serialize.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 Serialize `datetime`, `date`, and `time` values with their standard-library ISO 8601 representation in the `default` method of scrapy/utils/serialize.py, keeping `datetime` ahead of `date`
- [ ] T004 Remove the now-unused `DATE_FORMAT` / `TIME_FORMAT` class attributes from scrapy/utils/serialize.py

**Checkpoint**: The encoder emits ISO 8601 for temporal values and unchanged output for everything else.

---

## Phase 3: User Story 1 - Parseable date/time values in JSON output (Priority: P1) 🎯 MVP

**Goal**: JSON/JSON Lines feeds emit ISO 8601 temporal strings.

**Independent Test**: Encode a `datetime`, `date`, and `time`, and export an item containing a `datetime` to JSON Lines; all temporal outputs parse as ISO 8601.

### Tests for User Story 1

- [ ] T005 [P] [US1] Update the expected `datetime` string from the space-separated form to the `T`-separated ISO 8601 form in tests/test_utils_serialize.py
- [ ] T006 [P] [US1] Update the exported `datetime` expectations in tests/test_exporters.py for the JSON and JSON Lines exporters

### Implementation for User Story 1

- [ ] T007 [US1] Verify `JsonItemExporter` and `JsonLinesItemExporter` in scrapy/exporters.py emit ISO 8601 without code changes

**Checkpoint**: JSON feed output uses ISO 8601 temporal strings.

---

## Phase 4: User Story 2 - Unambiguous time values in periodic log output (Priority: P2)

**Goal**: The periodic log's JSON output uses ISO 8601 temporal strings.

**Independent Test**: Emit a periodic log timing record and parse the logged JSON; temporal values are ISO 8601.

### Tests for User Story 2

- [ ] T008 [P] [US2] Confirm the timing assertions still hold and tighten them to ISO 8601 parsing in tests/test_extension_periodic_log.py

### Implementation for User Story 2

- [ ] T009 [US2] Verify `PeriodicLog` in scrapy/extensions/periodic_log.py requires no code change

**Checkpoint**: Periodic log timing/stats output uses ISO 8601 temporal strings.

---

## Phase 5: User Story 3 - Round-trip safety for consumers (Priority: P3)

**Goal**: Serialized temporal values round-trip losslessly.

**Independent Test**: Serialize an aware `datetime` with microseconds, parse it back with a standard ISO 8601 parser, and compare.

### Tests for User Story 3

- [ ] T010 [P] [US3] Extend the encoder coverage in tests/test_utils_serialize.py with microsecond and timezone-aware round-trip cases

### Implementation for User Story 3

- [ ] T011 [US3] Confirm sub-second and UTC-offset preservation in the temporal branches of scrapy/utils/serialize.py

**Checkpoint**: Serialized temporal values round-trip to equal values.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T012 [P] Document the ISO 8601 temporal output in docs/ for the JSON exporters
- [ ] T013 [P] Add a release note describing the format change
- [ ] T014 Run the targeted test modules named in this file and the scenarios in quickstart.md

---

## Dependencies & Execution Order

- Setup (Phase 1) → Foundational (Phase 2) → User Stories (Phase 3–5) → Polish (Phase 6)
- Foundational blocks all user stories; user stories are independent of each other.
- Within each story: tests first, then verification of the delegated consumer.

## Parallel Opportunities

- T001/T002, T005/T006, T012/T013 are independent and can run in parallel.

## Implementation Strategy

Complete Setup and Foundational, then deliver User Story 1 as the MVP; User Stories 2 and 3
confirm the delegated consumers and the round-trip guarantee without additional production
change.
