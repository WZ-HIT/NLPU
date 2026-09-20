## Why

The regression tests added for the `open_in_browser` ReDoS fix can report false
failures on slow or loaded CI workers, and the comment exploit input currently
contains a closing comment marker that can let a vulnerable implementation
finish after one long scan instead of exercising the pathological failure mode.
The tests therefore need to be made deterministic and effective without
changing runtime behavior.

## What Changes

- Stabilize the ReDoS timing assertion so it still distinguishes a safe
  implementation from catastrophic backtracking without depending on a tight,
  process-wide CPU-time budget.
- Correct the unterminated-comment exploit body used by
  `test_open_in_browser_redos_comment` so the vulnerable
  `<!--.*?-->`-style pattern must perform repeated failed searches.
- Keep the existing comment-preservation and `<head>` ReDoS coverage aligned
  with the corrected helper.

## Capabilities

### New Capabilities

None. This is a test-only change and does not alter observable product
behavior.

### Modified Capabilities

None. No requirement under `openspec/specs/` changes.

## Impact

- Test code: `tests/test_utils_response.py` only.
- Runtime code, public APIs, dependencies, and user-visible behavior are
  unchanged.
