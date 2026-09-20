# Tasks: Fix open_in_browser ReDoS Test Flakiness and a Broken Exploit Input

**Input**: Design documents from `specs/001-fix-redos-test-flakiness/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/redos-regression-contract.md

**Scope note**: This feature is test-only unless exploit validation exposes a real product defect (FR-008). Only `tests/` files are expected to change.

## Phase 1: Setup

- [ ] T001 Locate the current regression surface and record the exact symbols in `tests/test_utils_response.py` (`_assert_open_in_browser_is_fast`, `test_open_in_browser_redos_comment`, `test_open_in_browser_redos_head`) and the end-to-end touch point in `tests/test_commands.py` (`TestViewCommand`).
- [ ] T002 [P] In a scratch harness outside the repository, record baseline cost of the shipped `open_in_browser` in `scrapy/utils/response.py` and of the removed patterns `<!--.*?-->` and `(<head(?:>|\s.*?>))` on the current exploit bodies, to confirm which body fails to attack its target (research D2/D3).

## Phase 2: Foundational

**Purpose**: Shared harness pieces that every regression test depends on.

- [ ] T003 Add test-local helpers in `tests/test_utils_response.py`: an exploit-body validity predicate (no early match for the target removed pattern) and a cost helper that compares the shipped implementation at a base size against a size multiple, per contracts/redos-regression-contract.md C2/C3.
- [ ] T004 Refactor `_assert_open_in_browser_is_fast` in `tests/test_utils_response.py` to use the cost helper instead of the hardcoded `max_cpu_time = 0.2` CPU budget, keeping an absolute value only as a wide smoke check (research D1).

**Checkpoint**: Validated cost and validity helpers exist; no user story work before this completes.

## Phase 3: User Story 1 - ReDoS regression tests never fail because of machine speed (Priority: P1) 🎯 MVP

**Goal**: Deterministic ReDoS coverage for `open_in_browser`.

**Independent Test**: Run `pytest tests/test_utils_response.py -k "redos" -q` repeatedly (including under CPU contention); all runs pass, and reinstating a removed pattern in a scratch copy makes the matching test fail.

- [ ] T005 [US1] Update `test_open_in_browser_redos_comment` in `tests/test_utils_response.py` to use the machine-independent cost criterion from T004.
- [ ] T006 [P] [US1] Update `test_open_in_browser_redos_head` in `tests/test_utils_response.py` to use the machine-independent cost criterion from T004.
- [ ] T007 [US1] Verify determinism by running the ReDoS selection at least 20 consecutive times, including on a deliberately loaded worker, and confirm 20/20 pass (SC-001).
- [ ] T008 [US1] Verify detection by reinstating each removed pattern in a scratch copy only and confirming the corresponding ReDoS test fails (SC-003); revert the scratch change.

**Checkpoint**: User Story 1 is complete and independently demonstrable.

## Phase 4: User Story 2 - Exploit bodies genuinely exercise the patterns they guard against (Priority: P2)

**Goal**: No vacuous exploit body.

**Independent Test**: For each body, the validity predicate passes and the target removed pattern is observed to miss early matches.

- [ ] T009 [US2] Replace the comment exploit body in `tests/test_utils_response.py` so it no longer supplies a closing `-->` (currently `b"-><!--\x00" * 250_000 + b"->\n<!---->"`), per research D2.
- [ ] T010 [P] [US2] Re-validate and, if needed, resize the head exploit body `b"<head\t" * 80_000` in `tests/test_utils_response.py` using the T003 predicate and research D3.
- [ ] T011 [US2] Assert the validity predicate inside both ReDoS tests in `tests/test_utils_response.py` so a future early-terminating body fails the test instead of silently passing.

**Checkpoint**: Both exploit bodies are proven non-vacuous.

## Phase 5: User Story 3 - Viewer behavior is unchanged (Priority: P3)

**Goal**: No behavioral regression while touching the tests.

**Independent Test**: Existing viewer assertions pass unchanged.

- [ ] T012 [P] [US3] Confirm every pre-existing assertion in `tests/test_utils_response.py` (comment preservation, `test_inject_base_url` parametrization, base URL variants, `.txt` extension, `TypeError`) is retained unmodified in intent (SC-004).
- [ ] T013 [P] [US3] Run `pytest tests/test_commands.py -k "ViewCommand" -q` and confirm the `scrapy view` end-to-end path still renders the response and reports non-text responses unchanged.

**Checkpoint**: All stories independently functional.

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T014 [P] Update the comment in `tests/test_utils_response.py` that explains why exploit inputs are large so it describes the machine-independent criterion rather than a fixed time budget.
- [ ] T015 Run the full `tests/test_utils_response.py` module and confirm no test was skipped or relaxed to satisfy the new criterion (SC-004).
- [ ] T016 Validate the scenarios in `specs/001-fix-redos-test-flakiness/quickstart.md` end to end.

## Dependencies & Execution Order

- Phase 1 → Phase 2 → Phases 3–5 (US1 blocks US2 in practice, because US2's validity assertions are wired through the helpers introduced for US1; US3 is independent).
- T004 must precede T005/T006; T003 must precede T009/T010/T011.
- US3 (T012–T013) can run in parallel with US1/US2 once Phase 2 is done.

## Parallel Execution Examples

```bash
# US1 test updates (different test functions, same module - coordinate commits)
Task: "T006 [P] [US1] Update test_open_in_browser_redos_head in tests/test_utils_response.py"

# US3 verification alongside the test edits
Task: "T013 [P] [US3] Run pytest tests/test_commands.py -k ViewCommand -q"
```

## Implementation Strategy

MVP = User Story 1 (T001–T008): the ReDoS tests become deterministic while
still detecting the removed patterns. User Story 2 follows immediately and
makes the guarantee non-vacuous. User Story 3 is a regression safety net and
can be verified in parallel. Total: 16 tasks (Setup 2, Foundational 2, US1 4,
US2 3, US3 2, Polish 3).
