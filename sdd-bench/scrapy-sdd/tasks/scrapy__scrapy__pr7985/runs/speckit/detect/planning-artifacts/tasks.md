# Tasks: Rerun Internet-Dependent Test Failures

**Input**: `/workspace/specs/spec.md` and `/workspace/specs/plan.md`

## Phase 1: Setup

- [ ] T001 Inspect pytest dependencies and retry configuration in `pyproject.toml` and `tox.ini`
- [ ] T002 [P] Confirm the three modules containing `pytest.mark.requires_internet`

## Phase 2: Foundational

- [ ] T003 Configure retry support for pytest environments in `tox.ini`
- [ ] T004 Configure retry behavior for `requires_internet` in `pyproject.toml`

**Checkpoint**: Only Internet-dependent failures are retried.

## Phase 3: User Story 1 - Tolerate transient Internet failures (Priority: P1)

**Goal**: Retry transient failures without masking permanent failures.

**Independent Test**: Force an initial failure in a marked test and confirm retry behavior.

- [ ] T005 [US1] Cover `TestRealWebsite` in `tests/test_downloader_handler_twisted_http11.py`
- [ ] T006 [P] [US1] Cover `TestRealWebsite` in `tests/test_downloader_handler_twisted_http2.py`
- [ ] T007 [P] [US1] Cover `TestRealWebsite` in `tests/test_downloader_handler_httpx.py`
- [ ] T008 [US1] Confirm inherited tests in `tests/utils/bases/download_handlers_http.py` receive the policy through concrete subclasses

## Final Phase: Polish

- [ ] T009 Verify permanent failures still fail after retries
- [ ] T010 Verify non-marked tests are not retried
- [ ] T011 Document contributor-facing retry behavior

## Dependencies & Execution Order

T001 and T002 can run in parallel. T003 and T004 depend on T001. T005-T008 depend on T003 and T004. T009-T011 depend on User Story 1.

## Implementation Strategy

Implement shared configuration first, verify all three concrete `TestRealWebsite` classes, then confirm unrelated tests are unchanged.
