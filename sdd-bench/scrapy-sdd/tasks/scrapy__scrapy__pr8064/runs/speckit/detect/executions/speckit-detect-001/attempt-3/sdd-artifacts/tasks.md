---
description: "Task list for open_in_browser ReDoS regression test hardening"
---

# Tasks: open_in_browser ReDoS Regression Test Hardening

**Input**: Design documents in the mounted planning directory (`spec.md`, `plan.md`, `research.md`, `quickstart.md`)

**Prerequisites**: plan.md, spec.md, research.md

**Scope note**: Implementation is test-only. No task may modify
`scrapy/utils/response.py` or any other production file. Tests are not executed
during the planning phase.

## Phase 1: Setup

**Purpose**: Confirm the surface under test and the file that owns it.

- [ ] T001 Confirm the `open_in_browser` definition and the absence of vulnerable regexes in scrapy/utils/response.py, then record the finding in research.md
- [ ] T002 [P] Confirm the candidate test list in detection-draft.json matches every test reference to `open_in_browser` in tests/test_utils_response.py and tests/test_commands.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the evidence that decides the payload shape; blocks all user stories.

- [ ] T003 Document, next to each payload in tests/test_utils_response.py, the historical pattern it targets and why the payload forces super-linear work for that pattern
- [ ] T004 Reproduce the historical comment-removal and head-detection patterns in a scratch file outside the repository and confirm each payload fails to short-circuit them (evidence recorded in the task notes)
- [ ] T005 Decide and record in research.md whether the adversarial assertions stay timing-based with a generous budget or become timing-free (recommended: verify the payload deterministically, keep a generous safe-case budget)

**Checkpoint**: Payload validity is established before touching the assertions.

---

## Phase 3: User Story 1 - Trustworthy ReDoS regression signal (Priority: P1) 🎯 MVP

**Goal**: Repeated runs give the same verdict regardless of machine speed.

**Independent Test**: Run `python -m pytest tests/test_utils_response.py -k redos -q` 20 times on a loaded worker; every run passes.

- [ ] T006 [US1] Rework `_assert_open_in_browser_is_fast` in tests/test_utils_response.py so the verdict is reproducible on slow interpreters and loaded workers (T005 decision)
- [ ] T007 [US1] Keep the `_openfunc` callback assertion in the adversarial tests so the real code path is exercised, in tests/test_utils_response.py
- [ ] T008 [US1] Update the explanatory comment above the adversarial tests in tests/test_utils_response.py to describe the new oracle and budget

**Checkpoint**: The adversarial tests pass repeatedly and no longer depend on machine speed.

---

## Phase 4: User Story 2 - Exploit inputs that reproduce the vulnerability (Priority: P2)

**Goal**: Each payload provably drives the historical pattern it names.

**Independent Test**: Restore the historical pattern in a scratch copy and confirm the payload test fails quickly.

- [ ] T009 [US2] Replace or repair the broken payload in `test_open_in_browser_redos_comment` in tests/test_utils_response.py (T003/T004 evidence)
- [ ] T010 [US2] Verify and, if needed, repair the payload in `test_open_in_browser_redos_head` in tests/test_utils_response.py against `(<head(?:>|\s.*?>))`
- [ ] T011 [US2] Record the payload sizes, generated-byte counts, and the deliberate-regression failure result in the task notes referenced by spec.md SC-002

**Checkpoint**: Both payloads fail fast against the vulnerable patterns and pass quickly against the current implementation.

---

## Phase 5: User Story 3 - Behaviour coverage stays intact (Priority: P3)

**Goal**: No functional coverage is lost while hardening the security tests.

**Independent Test**: The pre-existing behaviour tests run unmodified and pass.

- [ ] T012 [US3] Confirm `test_inject_base_url`, `test_open_in_browser_preserves_html_comments`, `test_open_in_browser_keeps_base_url_of_response`, `test_open_in_browser_injects_base_when_only_in_comment`, `test_open_in_browser_injects_base_before_head_contents`, `test_open_in_browser_text_response_uses_txt_extension`, and `test_open_in_browser_raises_for_unsupported_response_type` in tests/test_utils_response.py are unchanged
- [ ] T013 [US3] Run `python -m pytest tests/test_commands.py -k TestViewCommand -q` to confirm the indirect `scrapy view` path still passes

**Checkpoint**: All three user stories are independently verifiable.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T014 Run the full module once (`python -m pytest tests/test_utils_response.py -q`) and record the outcome
- [ ] T015 Confirm `git status --short` shows no production-code change
- [ ] T016 Update the detection candidates in detection-draft.json if the implemented tests move or rename symbols

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Phase 1; blocks all user stories (T005 decides the assertion strategy).
- **User Story 1 (P1)**: depends on Phase 2.
- **User Story 2 (P2)**: depends on Phase 2; T009/T010 are independent of T006-T008.
- **User Story 3 (P3)**: depends on Phase 2 only.
- **Polish (Phase 6)**: depends on all desired stories.

### Parallel Opportunities

- T001/T002 (Phase 1) can run in parallel.
- T009 and T010 touch the same file but different tests; treat them as sequential in a single working copy.
- T012 and T013 can run in parallel with T006-T011 verification.

## Implementation Strategy

1. Complete Phase 1 and Phase 2 to establish payload evidence.
2. Land User Story 1 (MVP): deterministic adversarial tests.
3. Land User Story 2: repaired payloads.
4. Re-run User Story 3 checks and the full module before handing off.

## Notes

- No task requires network access; every payload is generated in memory.
- `[P]` marks tasks that touch different files or are read-only.
- The whole feature is a test-only change; any temptation to modify
  `scrapy/utils/response.py` means the payload evidence step was skipped.
