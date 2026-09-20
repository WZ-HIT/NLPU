# Detect Planning Spec: open_in_browser ReDoS test fixes

## Context

- Repository: `scrapy/scrapy`
- Pull request: `8064`
- Base commit: `3857c6906b2da51e12ca6005434512b7704fd659`
- PR title: Fix open_in_browser ReDoS test flakiness and a broken exploit input

## Scope

Plan only the detection of repository-relative test files relevant to the PR. Do not modify project code or tests and do not execute tests.

## Affected behavior

The PR targets the ReDoS regression coverage for
`scrapy.utils.response.open_in_browser`. The relevant regression tests assert
that crafted HTML inputs are processed quickly and therefore combine a timing
threshold with large exploit payloads. The PR addresses instability in that
timing-based assertion and repairs an exploit payload that does not exercise
the vulnerable regular expression as intended.

## Primary detection target

`tests/test_utils_response.py` directly imports and calls
`scrapy.utils.response.open_in_browser`. It owns the shared timing helper and
the two ReDoS exploit-input tests that define the reviewed behavior. No other
test module directly exercises this function or these payloads.

## Detection output

Emit one schema-only `detection-draft.json` containing a `candidates` array.
Each candidate must identify a repository-relative test path, the relevant
test symbols, and an evidence-based reason for inclusion.
