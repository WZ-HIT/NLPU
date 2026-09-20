# Phase 0 Research: Deterministic Response-Based File Path Test

## Decision 1: Root cause of the Windows flake

- **Decision**: The flake is caused by the test seeding the mocked store with
  `last_modified = time.time()` and then letting the pipeline compute
  `age = time.time() - last_modified` on the real clock.
- **Rationale**: On Windows the system clock advances in ~15 ms steps, so the
  two reads can be equal. The resulting age is `0`, and the freshness check
  (`age_days > self.expires`, with `FILES_EXPIRES = 0`) evaluates `0 > 0` as
  false, so the pre-existing file is reported as `uptodate` instead of being
  re-downloaded. On platforms with a fine clock the second read is larger, the
  age is positive, and the file is correctly re-downloaded.
- **Alternatives considered**: Treating this as a pipeline bug (rejected: the
  production behavior is correct and unchanged; only the test's time source is
  unrealistic), or blaming the async media pipeline (rejected: the freshness
  decision is synchronous in `FilesPipeline._onsuccess`).

## Decision 2: Fix strategy

- **Decision**: Give the mocked store record a `last_modified` value that is
  unambiguously in the past rather than "now", so the freshness check forces a
  download deterministically on every platform.
- **Rationale**: This keeps the test's intent (a response-less path that is
  skipped while expiry is disabled) while removing the dependence on clock
  resolution. It requires no new imports beyond what the module already uses,
  and it does not alter any assertion.
- **Alternatives considered**:
  - Sleeping between the mocked timestamp and the check: rejected, adds
    latency and is the class of fix the project is moving away from.
  - Retrying or tolerating either `downloaded` or `uptodate`: rejected, it
    weakens the assertion and hides real regressions.
  - Patching `time.time` for the whole test: rejected as broader than needed;
    stubbing the store record is more local and easier to read.
  - Raising `FILES_EXPIRES` above zero to change the comparison: rejected, that
    would invert the scenario the test is designed to cover.

## Decision 3: Regression surface

- **Decision**: The regression surface is the files-pipeline test module, with
  the images and media pipeline test modules as adjacent cover for the same
  shared code path.
- **Rationale**: `scrapy/pipelines/files.py` and `scrapy/pipelines/media.py`
  share the up-to-date/`stat_file` path; `ImagesPipeline` subclasses
  `FilesPipeline`. `tests/utils/media_pipelines.py` supplies the mocked
  download used by the target test.
- **Alternatives considered**: Considering only the single test method
  (rejected: the module shares helpers and mock data with sibling tests).

## Open questions

None. No `NEEDS CLARIFICATION` markers remained after specification, so no
research escalation was needed.
