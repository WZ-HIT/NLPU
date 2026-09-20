# Contract: `test_file_path_from_response`

This contract fixes the observable behavior the test must keep asserting after
the determinism fix. It is a test-level contract, not a production interface.

## Location

- Module: `tests/test_pipeline_files.py`
- Class: `TestFilesPipeline`
- Test: `test_file_path_from_response`

## Setup contract (inputs)

1. A `FilesPipeline` subclass whose `file_path` appends the extension guessed
   from the response `Content-Type` header when a response is supplied.
2. The pipeline is configured with `FILES_EXPIRES = 0`.
3. A request prepared for the item URL, carrying `Content-Type: application/pdf`.
4. `FSFilesStore.stat_file` is mocked to report a checksum and a last-modified
   timestamp for the response-less path.

## Behavior contract (assertions)

| # | Assertion | Must remain |
|---|-----------|-------------|
| 1 | `result["files"][0]["status"] == "downloaded"` | Yes |
| 2 | `result["files"][0]["path"].endswith(".pdf")` | Yes |
| 3 | The stored file content equals the mocked download payload | Yes |
| 4 | `files.inc_stats` and `get_media_requests` remain mocked | Yes |

## Determinism contract

- The mocked last-modified timestamp MUST make the freshness decision
  independent of the host clock's resolution: the computed age must be strictly
  greater than the configured expiry (`FILES_EXPIRES = 0`) for any realistic
  reading of the wall clock during the test.
- Introducing a sleep, retry loop, or tolerant assertion violates this contract.

## Out of scope

- Any production change in `scrapy/pipelines/files.py` or
  `scrapy/pipelines/media.py`.
- Renaming or moving the test.
