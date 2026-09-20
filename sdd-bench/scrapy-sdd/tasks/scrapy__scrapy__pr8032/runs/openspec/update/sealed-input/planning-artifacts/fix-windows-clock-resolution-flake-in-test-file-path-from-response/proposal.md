## Why

`TestFilesPipeline.test_file_path_from_response` can fail on Windows because
`time.time()` may have coarse resolution. The mocked `last_modified` value and
the later freshness check can land in the same clock tick, making an intended
expired file appear up to date with `FILES_EXPIRES=0`.

## What Changes

- Make the test's mocked cached-file timestamp unambiguously older than the
  freshness check even on platforms with coarse clock resolution.
- Preserve the test's purpose: verify that a response-derived file path is
  downloaded when the response-less path cannot be reused.
- Do not change production behavior, public APIs, dependencies, or test
  coverage.

## Capabilities

### New Capabilities

None. This is a test reliability fix with no product behavior change.

### Modified Capabilities

None. No existing requirement changes.

## Impact

- Test: `tests/test_pipeline_files.py`
- Production code: none
- Public APIs and dependencies: none
