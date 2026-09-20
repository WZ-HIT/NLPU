# Quickstart: Download Delay Crawl Coverage

## Prerequisites

- Install the project test dependencies for the active Python environment.
- Run commands from the repository root.

## Validation

Run the detected test nodes without changing test code:

```bash
pytest -q tests/test_crawl.py::TestCrawl::test_fixed_delay tests/test_crawl.py::TestCrawl::test_randomized_delay
```

Expected outcome: both tests pass and each delayed crawl performs multiple content-page visits. Confirm that the no-delay control still runs and that no production source files are changed.

## Detection Check

Confirm that `detection-draft.json` contains only a `candidates` array and that its paths are repository-relative test paths.
