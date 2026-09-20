# Tasks: Open Non-Text Responses in Browser via Content-Type

**Input**: Design documents from `/workspace/specs/`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, and `contracts/open-in-browser.md`

**Tests**: Automated utility and command-level tests are required by FR-011 and are included below. Do not run tests during this planning-only turn.

**Organization**: Tasks are grouped by user story so each priority slice remains independently testable.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the exact change surface and reusable test infrastructure before implementation.

- [ ] T001 Confirm the current behavior and integration points in `scrapy/utils/response.py`, `scrapy/commands/view.py`, `tests/test_utils_response.py`, and `tests/test_commands.py`
- [ ] T002 [P] Validate the browser-recording helper and PNG fixture in `tests/utils/cmdline.py` and `tests/sample_data/test_site/files/images/scrapy.png`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish extension resolution and response-class precedence used by every user story.

**⚠️ CRITICAL**: No user-story integration work should begin until this phase is complete.

- [ ] T003 Add a private media-type normalization and extension-resolution helper in `scrapy/utils/response.py`
- [ ] T004 Implement HTML, non-HTML text, and generic response classification precedence in `scrapy/utils/response.py` (depends on T003)

**Checkpoint**: The utility has one deterministic extension-resolution path for all response classes.

---

## Phase 3: User Story 1 - Open a downloaded non-text response in a browser (Priority: P1) 🎯 MVP

**Goal**: Generic responses with supported media types produce local browser targets with conventional extensions and unchanged bytes.

**Independent Test**: Open recorded PNG, JPEG, and PDF responses through the utility and through the command workflow, then verify extension selection, exact bytes, and successful command completion.

### Tests for User Story 1

- [ ] T005 [P] [US1] Add parametrized utility tests for `image/png`, `image/jpeg`, and `application/pdf` extension selection and byte preservation in `tests/test_utils_response.py`
- [ ] T006 [P] [US1] Update the command-level image case in `tests/test_commands.py` to expect a successful view and a `.png` browser target

### Implementation for User Story 1

- [ ] T007 [US1] Connect generic response bodies to the media-type extension resolver in `scrapy/utils/response.py` (depends on T003, T004)
- [ ] T008 [US1] Remove the non-text response rejection from `scrapy/commands/view.py` and delegate to the browser-opening utility

**Checkpoint**: A downloaded PNG, JPEG, or PDF can be opened through the utility and command workflow.

---

## Phase 4: User Story 2 - Preserve existing HTML and text behavior (Priority: P2)

**Goal**: HTML and non-HTML textual responses keep their existing preparation, extensions, and base-link behavior.

**Independent Test**: Run the existing HTML base-link, comment, doctype, performance, and textual response scenarios and confirm unchanged outcomes.

### Tests for User Story 2

- [ ] T009 [US2] Add or retain regression assertions for HTML base-link injection, comments, doctypes, and `.txt` textual responses in `tests/test_utils_response.py`

### Implementation for User Story 2

- [ ] T010 [US2] Verify response-class precedence in `scrapy/utils/response.py` keeps HTML preparation ahead of generic media-type resolution and keeps non-HTML text at `.txt`

**Checkpoint**: The new generic path does not alter any existing HTML or text outcome.

---

## Phase 5: User Story 3 - Fail clearly when the media type is unusable (Priority: P3)

**Goal**: Missing, malformed, and unknown media types fail clearly without producing or opening a browser target.

**Independent Test**: Attempt to open generic responses with no header, malformed media types, and unknown media types; verify explicit errors and zero browser-opener calls.

### Tests for User Story 3

- [ ] T011 [US3] Add utility tests for missing, malformed, parameterized-valid, and unknown `Content-Type` values in `tests/test_utils_response.py`

### Implementation for User Story 3

- [ ] T012 [US3] Implement explicit unsupported-response handling in `scrapy/utils/response.py` when extension resolution fails (depends on T003)

**Checkpoint**: Unsupported generic responses fail predictably and never call the browser opener.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, validation, and final review across all stories.

- [ ] T013 [P] Update `docs/topics/debug.rst` to describe non-text browser viewing and unsupported media-type behavior
- [ ] T014 [P] Add the user-visible change note to `docs/news.rst`
- [ ] T015 Run `pytest tests/test_utils_response.py -k open_in_browser`
- [ ] T016 Run `pytest tests/test_commands.py -k TestViewCommand`
- [ ] T017 [P] Run the repository's static checks for `scrapy/utils/response.py`, `scrapy/commands/view.py`, `tests/test_utils_response.py`, and `tests/test_commands.py`
- [ ] T018 Validate all scenarios described in `specs/quickstart.md`
- [ ] T019 Review the final implementation diff for unintended changes outside the utility, command, documentation, and focused test files

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational and delivers the MVP.
- **User Story 2 (Phase 4)**: Depends on Foundational; can be developed independently but should be merged after or alongside US1 because both validate behavior in `scrapy/utils/response.py`.
- **User Story 3 (Phase 5)**: Depends on Foundational and can be developed independently; preserve merge order with other changes in `scrapy/utils/response.py` and `tests/test_utils_response.py`.
- **Polish (Phase 6)**: Depends on all desired user stories.

### User Story Dependencies

- **US1**: No dependency on US2 or US3.
- **US2**: No functional dependency on US1, but its regression coverage protects the shared utility.
- **US3**: No functional dependency on US1 or US2, but its error contract is part of the same resolver.

### Within Each User Story

- Add or update tests before implementation.
- Resolve extension behavior before integrating command behavior.
- Complete utility behavior before command validation.
- Preserve HTML and text behavior before moving to documentation.

### Parallel Opportunities

- T002 can run alongside T001.
- T005 and T006 are in different test files and can run together.
- T013 and T014 are in different documentation files and can run together.
- T017 is independent of documentation updates.
- Different user stories can be assigned to different developers only if changes to the shared utility and utility test file are coordinated.

---

## Parallel Example: User Story 1

```text
Task: "T005 [P] [US1] Add generic media-type tests in tests/test_utils_response.py"
Task: "T006 [P] [US1] Update the command image test in tests/test_commands.py"
```

## Parallel Example: Polish

```text
Task: "T013 [P] Update docs/topics/debug.rst"
Task: "T014 [P] Update docs/news.rst"
Task: "T017 [P] Run static checks for changed Python files"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete the setup and foundational phases.
2. Complete T005 through T008.
3. Validate recorded PNG, JPEG, and PDF cases through the utility.
4. Validate the command workflow with the PNG fixture.
5. Stop and review the MVP before adding broader regression and documentation work.

### Incremental Delivery

1. Foundational resolver and precedence are complete.
2. US1 adds generic response support and command delegation.
3. US2 proves HTML and text behavior did not regress.
4. US3 pins explicit failure behavior for unusable media types.
5. Polish updates documentation and runs focused validation.

### Parallel Team Strategy

1. Complete Setup and Foundational work together.
2. Assign US1 utility tests and command tests to different developers.
3. Coordinate all edits to `scrapy/utils/response.py` and `tests/test_utils_response.py` because those files are shared across stories.
4. Finish with documentation and focused test validation after all behavior changes are merged.

---

## Notes

- `[P]` means the task can run in parallel with other marked tasks because it uses a different file and has no incomplete dependency.
- Story labels map each user-story task to its specification priority.
- No task authorizes running tests during the planning-only turn that produced this file.
- All behavior changes remain in the existing utility and command modules; no new package or service is introduced.

## Format Validation

All tasks use the required checklist format: markdown checkbox, sequential task ID, optional `[P]`, optional story label, and an exact file path or explicit validation command.
