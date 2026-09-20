# Detection Spec: scrapy PR #8073

## Input

- Repository: `scrapy/scrapy`
- Pull request: `8073` — "Re-enable tests with DirtyReactorAggregateError comments."
- Base commit: `11079cb1c85b9e75a39a7269943c69d1a975d485`
- Task input: `/task-input/task.md`
- Stage scope: cc-sdd Detect planning phases only (spec, detect).

## Objective

Identify the candidate test files (and the specific test symbols) that the pull
request touches or exercises, and record them in `detection-draft.json` so a
later stage can run only the relevant tests.

## Constraints observed

- No tests were executed (blocked-by-policy; `pytest`/`tox`/`unittest` are denied).
- No project code or tests were modified; the repository is read-only in this stage.
- All planning artifacts are written only to the mounted planning directory
  (`/workspace/.kiro/specs`, bind-mounted from the run's `planning-artifacts`).

## Method

1. Read the PR task and note the exact wording: re-enable tests that were skipped
   with a `DirtyReactorAggregateError` comment.
2. Search the repository for every occurrence of `DirtyReactorAggregateError`
   (case-insensitive) and for the referenced Twisted ticket (`10279`).
3. Determine, for each skip site, which concrete test modules actually execute
   the affected tests (base mixin vs. concrete subclasses).
4. Emit one candidate per relevant repository-relative test path with the
   affected symbols and a rationale.

## Findings

Exactly three `DirtyReactorAggregateError` skip comments exist in the repository:

| Location | Symbol | Gate |
| --- | --- | --- |
| `tests/utils/bases/download_handlers_http.py:362` | `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd` | `reactor_pytest == "asyncio" and sys.platform == "win32"` |
| `tests/utils/bases/download_handlers_http.py:380` | `TestHttpBase.test_timeout_download_from_spider_server_hangs` | `reactor_pytest == "asyncio" and sys.platform == "win32"` |
| `tests/test_downloader_handler_twisted_ftp.py:178` | `TestFTP.test_invalid_credentials` | `reactor_pytest == "asyncio" and sys.platform == "win32"` |

The two `download_handlers_http.py` tests live on `TestHttpBase`, which is
inherited (directly or via `TestHttpsBase`) by the concrete test classes in:

- `tests/test_downloader_handler_httpx.py` (`TestHttp`, `TestHttps`, `TestHttp2`)
- `tests/test_downloader_handler_twisted_http11.py` (`TestHttp`, `TestHttps`)
- `tests/test_downloader_handler_twisted_http2.py` (`TestHttp2`)

Both definition sites and their concrete execution modules are recorded as
candidates, since re-enabling the base tests only has an effect when one of the
inheriting modules runs.

## Out of scope

- Implementation of the re-enable change (no code or test edits).
- Test execution or result reporting.
- Non-test source files.
