# Implementation Plan

> Detect-stage note: tasks 1-3 describe the code change requested by the pull
> request and are recorded for the later implementation stage. Task 4 is the
> detect-stage work performed here. No task in this file was executed during the
> detect stage.

- [ ] 1. Stabilize the ReDoS CPU-time guard in `tests/test_utils_response.py`
  - Enlarge the adversarial payloads so a vulnerable implementation is clearly
    super-linear while a linear one stays in the low milliseconds.
  - Assert a CPU-time budget (`time.process_time`) with an explicit safety margin,
    documented inline next to the budget constant.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - _Boundary: ReDoS payload tests_

- [ ] 2. Repair the exploit payload that no longer witnesses its pattern
  - Re-derive the comment and head payloads from the recheck playground witnesses
    for `/<!--.*?-->/` and `/(<head(?:>|\s.*?>))/`.
  - Keep pattern, source, and purpose in the comment above each payload.
  - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - _Boundary: ReDoS payload tests_

- [ ] 3. Preserve the surrounding `open_in_browser()` coverage
  - Leave `test_open_in_browser`, `test_inject_base_url`, the comment/head
    injection cases, the `.txt` extension case, the `TypeError` case, and the
    `get_base_url` / `get_meta_refresh` / `response_status_message` tests in
    place and passing.
  - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - _Boundary: Behaviour tests_
  - _Depends: 1_

- [ ] 4. Record candidate test files for the detect stage
  - Scan the import and call graph of the changed module and list every test
    module that drives `open_in_browser`.
  - Emit a single JSON object with a `candidates` array (repository-relative
    path, symbols, reason) as the detection draft.
  - Do not modify project code or tests and do not execute any test suite.
  - _Requirements: 4.1, 4.2, 4.3_
  - _Boundary: Detection draft_
