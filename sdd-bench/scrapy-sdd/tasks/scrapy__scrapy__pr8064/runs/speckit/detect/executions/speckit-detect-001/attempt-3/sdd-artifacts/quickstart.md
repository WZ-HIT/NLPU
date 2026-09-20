# Quickstart: Validating the open_in_browser ReDoS Test Hardening

This guide describes how to validate the change during the implementation
phase. Nothing in this document was executed while producing the planning
artifacts.

## Prerequisites

- Repository checkout at base commit `3857c6906b2da51e12ca6005434512b7704fd659`.
- Python >= 3.10 environment with the project's test dependencies installed
  (Scrapy, Twisted, pytest, `tests/mockserver` requirements).
- No network access needed; the payloads are generated in memory.

## Scenario 1 - Behaviour coverage still passes

```bash
python -m pytest tests/test_utils_response.py -k "open_in_browser or inject_base_url" -q
```

Expected: all `open_in_browser` and `inject_base_url` tests pass, including
base-tag placement, comment preservation, `.txt` output, and `TypeError` cases.

## Scenario 2 - Adversarial tests are not flaky

```bash
for i in $(seq 1 20); do python -m pytest tests/test_utils_response.py -k redos -q; done
```

Expected: 20 consecutive passing runs with no timing-related failure, on an
idle and (if available) a loaded worker.

## Scenario 3 - The payloads really detect the regression

1. Temporarily restore the historical comment-removal pattern
   (`<!--.*?-->`) and head-detection pattern (`(<head(?:>|\s.*?>))`) in a scratch
   copy of `scrapy/utils/response.py`.
2. Run `python -m pytest tests/test_utils_response.py -k redos -q` against that
   scratch copy.

Expected: at least one adversarial test fails quickly; the run must not hang
until the per-test timeout. Revert the scratch copy afterwards - no production
change is part of this feature.

## Scenario 4 - Indirect CLI surface

```bash
python -m pytest tests/test_commands.py -k TestViewCommand -q
```

Expected: `scrapy view` still writes the served HTML body to a `file://` path.

## Done criteria

- All four scenarios meet their expected outcome.
- `git status --short` shows no production-code modification.
- The detection candidates used for these runs match
  [detection-draft.json](./detection-draft.json).
