# Tasks: Generalize Internal Component Construction

**Input**: `specs/spec.md` and `specs/plan.md`

**Tests**: Candidate tests are identified for implementation validation, but
this planning-only task does not run tests.

## Phase 1: Setup

- [ ] T001 Confirm all internal direct `from_crawler()` call sites in `scrapy/`.
- [ ] T002 Record constructor arguments and lifecycle exceptions in `scrapy/crawler.py`.

## Phase 2: Foundational

- [ ] T003 Verify `build_from_crawler()` construction precedence and `None` handling in `scrapy/utils/misc.py`.
- [ ] T004 Confirm no public API or settings schema change is required.

## Phase 3: User Story 1 - Construct optional components consistently (P1)

**Goal**: Make internal component construction honor either constructor form.

**Independent Test**: Construct one `__init__()`-only component and one
`from_crawler()` component through each applicable setup path.

- [ ] T005 [US1] Replace direct downloader middleware manager construction in `scrapy/core/downloader/__init__.py`.
- [ ] T006 [US1] Replace direct spider middleware and item processor construction in `scrapy/core/scraper.py`.
- [ ] T007 [US1] Replace direct log formatter and extension manager construction in `scrapy/crawler.py`.
- [ ] T008 [P] [US1] Replace mail sender construction in `scrapy/extensions/statsmailer.py`.
- [ ] T009 [P] [US1] Replace mail sender construction in `scrapy/extensions/memusage.py`.
- [ ] T010 [P] [US1] Replace robots parser construction in `scrapy/downloadermiddlewares/robotstxt.py`.
- [ ] T011 [US1] Update imports only where `build_from_crawler()` is newly required.
- [ ] T012 [US1] Add or update focused regression coverage in the candidate test files listed in `detection-draft.json`.
- [ ] T013 [US1] Verify `from_crawler()`-based components still call that constructor with the crawler and component-specific arguments.
- [ ] T014 [US1] Verify `__init__()`-only components are constructed without receiving the crawler implicitly.

## Phase 4: Polish

- [ ] T015 Review all remaining direct `from_crawler()` calls and document explicit lifecycle exclusions.
- [ ] T016 Confirm no project code or tests were changed during planning.
- [ ] T017 Validate exactly one `detection-draft.json` exists under `specs/` and contains only `path`, `symbols`, and `reason` candidate fields.

## Dependencies

- T001-T004 precede all user-story work.
- T005-T010 depend on T003.
- T012-T014 depend on T005-T011.
- T015-T017 follow implementation and validation.

## Parallel Opportunities

- T008, T009, and T010 affect different production files and can run in parallel.
- Candidate test additions can be split by test file after production call-site changes are settled.

## Implementation Strategy

1. Convert one component family and verify its constructor behavior.
2. Convert the remaining families.
3. Run the focused test set from `detection-draft.json`.
4. Review lifecycle exceptions before declaring the refactor complete.
