# Tasks: Merge LxmlLinkExtractor Test Classes

**Input**: Design documents from `/workspace/specs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Test updates are the subject of this feature. Test execution is listed as later validation and is not performed during planning.

**Organization**: Tasks are grouped by the single user story and preserve independent verification of the public extractor suite and the internal parser extractor suite.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the bounded test-only scope before editing.

- [ ] T001 Confirm the affected module and current class inventory in `tests/test_linkextractors.py`
- [ ] T002 Confirm that `scrapy/linkextractors/lxmlhtml.py` exposes `LxmlLinkExtractor` as the only public extractor implementation

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the behavior-preservation baseline for the consolidation.

**Critical**: Complete this phase before changing the test class structure.

- [ ] T003 Record the 32 shared test names, 6 LxmlLinkExtractor test names, and 3 LxmlParserLinkExtractor test names from `tests/test_linkextractors.py`
- [ ] T004 Verify the shared setup fixture and conditional skip marker in `tests/test_linkextractors.py` are retained during restructuring

**Checkpoint**: The target symbols and behavior-preservation constraints are known.

---

## Phase 3: User Story 1 - Maintain one discoverable link extractor test suite (Priority: P1) MVP

**Goal**: Merge the hidden shared base and concrete LxmlLinkExtractor tests into one discoverable class.

**Independent Test**: Collect and run `tests/test_linkextractors.py`; one class must cover all 38 existing LxmlLinkExtractor tests while the 3 parser tests remain separate.

### Implementation for User Story 1

- [ ] T005 [US1] Convert the shared behavior methods from `Base.TestLinkExtractorBase` into the single LxmlLinkExtractor test class in `tests/test_linkextractors.py`
- [ ] T006 [US1] Move the 6 extractor-specific test methods and `extractor_cls` assignment into the same class in `tests/test_linkextractors.py`
- [ ] T007 [US1] Remove the `Base` wrapper and inheritance that exists only to hide the shared tests in `tests/test_linkextractors.py`
- [ ] T008 [US1] Preserve `test_canonicalize_once_per_link`, `test_link_restrict_text`, `test_skip_bad_links`, and the three `_link_allowed` tests with their existing names, assertions, and marker in `tests/test_linkextractors.py`
- [ ] T009 [US1] Keep `TestLxmlParserLinkExtractor` and its 3 tests separate and behaviorally unchanged in `tests/test_linkextractors.py`

**Checkpoint**: The public extractor suite is consolidated and independently verifiable.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Validate preservation and scope containment.

- [ ] T010 Validate the completed test inventory against the 38 LxmlLinkExtractor and 3 LxmlParserLinkExtractor baseline in `tests/test_linkextractors.py`
- [ ] T011 Run `pytest --collect-only tests/test_linkextractors.py` and confirm the consolidated class is discoverable
- [ ] T012 Run `pytest tests/test_linkextractors.py` and confirm no behavior regressions
- [ ] T013 Review the final diff and confirm that no production file or unrelated test file changed

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup.
- **User Story 1 (Phase 3)**: Depends on Foundational.
- **Polish (Phase 4)**: Depends on User Story 1.

### Within User Story 1

- Merge shared methods before removing the base wrapper.
- Move extractor-specific methods before final collection validation.
- Leave the parser extractor suite untouched throughout.

### Parallel Opportunities

None. All implementation changes affect the class structure of the same file, so parallel edits would create conflicting work.

---

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational tasks.
2. Complete User Story 1.
3. Validate collection and run the targeted test file.
4. Review the diff to prove that only the intended test module changed.

### Incremental Delivery

This feature has one independently deliverable increment: the single consolidated LxmlLinkExtractor test class. The parser extractor suite provides a secondary invariant to verify during the same change.

## Notes

- Preserve test names whenever possible so CI history remains comparable.
- Do not change production code.
- Do not drop conditional skip behavior.
- This planning run intentionally does not execute the validation tasks.
