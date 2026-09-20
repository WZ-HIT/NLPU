# Implementation Plan

> Detect-stage plan only. Tasks 1-2 are completed by this planning run; tasks 3-4 are
> deferred to the update stage and must not be executed here.

- [x] 1. Analyze the selector type resolution path in `scrapy/selector/unified.py` and the
      parsel nested-selector construction rules.
  - Confirm that `response is None` forces `type="html"` for nested selectors.
  - Confirm parsel derives `"json"` for `dict`/`list`/valid-JSON roots and `"html"`
    otherwise.
  - _Requirements: 1.1, 1.5, 1.6_

- [x] 2. Locate candidate test files for nested selector type verification and record them
      in `detection-draft.json`.
  - Emit exactly one `detection-draft.json` under the planning mount (`.kiro/specs/`).
  - Record repository-relative test paths with symbols and reasons.
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 3. Update production code so that `Selector` passes `type=None` to parsel when no
      response is available, keeping `"html"` only for `HtmlResponse`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_

- [ ] 4. Add or extend regression tests in the candidate files for nested JSON selector
      chaining.
  - _Requirements: 1.5, 2.1_
  - _Depends: 3_
