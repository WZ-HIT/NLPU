---

description: "Task list for browser preview of non-text responses"
---

# Tasks: Browser Preview for Non-Text Responses

**Input**: Design documents from `/workspace/specs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included - the acceptance criteria are behavioral, and the project's
existing suites already own these code paths.

**Organization**: Grouped by user story so each story is independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3
- Every task names the exact repository-relative file it touches

## Path Conventions

Single project: `scrapy/` (library and CLI), `tests/` (suite), `docs/`.

---

## Phase 1: Setup

- [ ] T001 Confirm the current failure modes and call sites of the preview helper in `scrapy/utils/response.py`, `scrapy/commands/view.py`, and `scrapy/shell.py`
- [ ] T002 [P] Confirm the standard-library media-type registry covers the target families (image, document, archive/octet-stream) with no new dependency
- [ ] T003 [P] Confirm the owning test entry points: `tests/test_utils_response.py` and `TestViewCommand` in `tests/test_commands.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Warning**: No user story work can begin until this phase is complete.

- [ ] T004 Define the extension-resolution rule in `scrapy/utils/response.py`: read `Content-Type`, strip parameters, look up a suffix, fall back to one documented generic suffix when missing/unmapped (FR-002, FR-005)
- [ ] T005 [P] Fix the call contract for both entry points in `specs/contracts/open_in_browser.md` (helper guarantees + "no response type is refused" for `scrapy view`)
- [ ] T006 Record the fallback suffix and the expectations for the mocked non-text route used by `tests/test_commands.py`

---

## Phase 3: User Story 1 - Preview a non-text response from spider code (Priority: P1) (MVP)

**Goal**: `open_in_browser` writes any response body to a temp file whose suffix
comes from `Content-Type` and opens it, instead of raising `TypeError`.

**Independent Test**: Non-text `Response` with `Content-Type: image/png` opens a
`.png` file containing the exact body; no exception.

- [ ] T007 [P] [US1] Add the non-text preview test in `tests/test_utils_response.py` (plain `Response`, `image/png`, asserts `.png` and byte-identical body)
- [ ] T008 [P] [US1] Update the unsupported-type expectations in `tests/test_utils_response.py` (`test_open_in_browser`, `test_open_in_browser_raises_for_unsupported_response_type`) to assert the new behavior
- [ ] T009 [P] [US1] Keep the text/HTML assertions in `tests/test_utils_response.py` (`.txt` extension, base-tag, comment, Redos tests) as regression coverage
- [ ] T010 [US1] Implement the media-type-driven extension branch in `scrapy/utils/response.py::open_in_browser`, replacing the `raise TypeError(...)` fallback and leaving the HTML/text branches untouched
- [ ] T011 [US1] Keep `response.body` byte-for-byte in the written file and invoke the opener once with `file://<path>` (FR-009)
- [ ] T012 [US1] Update the helper docstring in `scrapy/utils/response.py` to document non-text previews

**Checkpoint**: The helper alone delivers the feature; validate before continuing.

---

## Phase 4: User Story 2 - scrapy view opens non-text resources (Priority: P2)

**Goal**: The CLI no longer refuses non-text responses.

**Independent Test**: `scrapy view` on the non-text test-server route exits 0 and
opens the fetched bytes.

- [ ] T013 [P] [US2] Update `TestViewCommand.test_non_text_response` in `tests/test_commands.py` to assert a successful opened preview instead of the refusal message
- [ ] T014 [P] [US2] Keep `TestViewCommand.test_view` in `tests/test_commands.py` green as the HTML regression check
- [ ] T015 [US2] Remove the non-text refusal from `scrapy/commands/view.py::_print_response` (FR-006)
- [ ] T016 [US2] Verify `--spider`/`--no-redirect` handling in `scrapy/commands/view.py` is unchanged
- [ ] T017 [US2] Update the `view` command docs in `docs/topics/commands.rst`

---

## Phase 5: User Story 3 - Deterministic fallback for unusable media types (Priority: P3)

**Goal**: Missing, empty, or unknown `Content-Type` never blocks a preview.

**Independent Test**: No-header and unmapped-media-type responses both open a
file with the fallback suffix and the exact body.

- [ ] T018 [P] [US3] Add fallback coverage in `tests/test_utils_response.py` (no `Content-Type`, unmapped media type)
- [ ] T019 [P] [US3] Add parameterized coverage in `tests/test_utils_response.py` for `Content-Type` with parameters (e.g. `image/svg+xml; charset=utf-8`)
- [ ] T020 [US3] Make the fallback path in `scrapy/utils/response.py` total (FR-005, SC-003)
- [ ] T021 [US3] Normalize header values defensively in `scrapy/utils/response.py` (bytes/str, whitespace) before lookup

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T022 [P] Add a release-notes entry in `docs/news.rst`
- [ ] T023 [P] Cross-check the `view` shell binding in `scrapy/shell.py` against the new contract (FR-010)
- [ ] T024 Re-run `specs/quickstart.md` scenarios (deferred: this planning stage runs with tests disabled)

---

## Dependencies & Execution Order

- **Setup** -> **Foundational** -> user stories -> **Polish**.
- US1 is the MVP and unblocks US2 end-to-end; US3 hardens the same branch as US1.
- Within each story, tests are written first and must fail before implementation.
- The HTML branch must never be restructured; its tests are regression guards.

## Parallel Opportunities

- T002/T003 with T001; T005/T006 with T004.
- Test-first tasks T007-T009, T013-T014, T018-T019 across the three stories.
- T022/T023 once behavior is settled. The two test modules never conflict.

## Implementation Strategy

1. Foundation + US1 -> Python helper usable (MVP).
2. US2 -> `scrapy view` covers the CLI half of the report.
3. US3 -> exotic/missing media types handled deterministically.
4. Polish -> release notes and shell-binding cross-check.

## Notes

- [P] tasks touch different files or are pure documentation/analysis.
- This planning stage must not run the test suite (`SDD_AGENT_NO_TESTS=1`) and
  must not modify repository source or test files.
