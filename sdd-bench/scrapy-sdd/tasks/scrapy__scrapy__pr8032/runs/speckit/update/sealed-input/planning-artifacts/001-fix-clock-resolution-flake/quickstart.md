# Phase 1 Quickstart: Deterministic Response-Based File Path Test

Validation guide for the response-based file path determinism fix. It proves
the behavior described in `spec.md` and the design in `plan.md`.

## Prerequisites

- Repository checkout at the base commit of the change.
- A Python environment where the project's test extras are installed so that
  `pytest` and the Twisted/Scrapy test helpers import successfully.
- No network access is required; the store and download are mocked.

## Scenario 1 - The target test stays green on a coarse clock

Run the single test from the repository root:

```bash
pytest tests/test_pipeline_files.py::TestFilesPipeline::test_file_path_from_response -q
```

Expected outcome:

- The test passes with `status == "downloaded"` and a stored path ending in
  `.pdf`.
- Repeating the run (e.g. several consecutive invocations) produces the same
  pass result, with no `uptodate` result and no added delay.

## Scenario 2 - No regression in the surrounding module

```bash
pytest tests/test_pipeline_files.py -q
```

Expected outcome: every test in the module passes, including the sibling path,
custom-path, and expiry tests.

## Scenario 3 - Adjacent coverage for the shared code path

```bash
pytest tests/test_pipeline_media.py tests/test_pipeline_images.py -q
```

Expected outcome: all tests pass; the shared media/files freshness and path
logic is unaffected.

## Checklist

- [ ] Scenario 1 passes and reports `downloaded` on every run.
- [ ] Scenario 2 passes with no skipped or weakened assertions.
- [ ] Scenario 3 passes.
- [ ] No sleep, retry, or clock-tolerance logic was introduced by the change.
- [ ] No file under `scrapy/` was modified.

See `data-model.md` for the exact fields involved and `contracts/test-contract.md`
for the assertion contract this change must preserve.
