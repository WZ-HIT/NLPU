# Research & Design Decisions

## Summary

- **Feature**: `reenable-dirtyreactor-skipped-tests`
- **Discovery Scope**: Extension (existing test suite maintenance, brownfield)
- **Key Findings**:
  - The base commit contains exactly three `DirtyReactorAggregateError` comment sites, all in test code: two in `tests/utils/bases/download_handlers_http.py` and one in `tests/test_downloader_handler_twisted_ftp.py`.
  - All three are inline `pytest.skip(...)` guards gated on `reactor_pytest == "asyncio" and sys.platform == "win32"`, referencing Twisted ticket 10279.
  - The two HTTP tests live on the `TestHttpBase` ABC and are therefore executed through the concrete httpx, HTTP/1.1 and HTTP/2 modules, which the pull request does not need to edit.

## Research Log

### Which tests carry a `DirtyReactorAggregateError` comment?

- **Context**: The pull request title claims to re-enable "tests with DirtyReactorAggregateError comments", so the candidate set depends on locating every such comment in the snapshot.
- **Sources Consulted**: Repository snapshot at `/workspace` (base commit `11079cb1c85b9e75a39a7269943c69d1a975d485`); case-insensitive search for `dirtyreactor` / `dirty reactor` across all files outside `.git`; search for the Twisted ticket URL `10279`.
- **Findings**: Three hits, all `pytest.skip("This test produces DirtyReactorAggregateError on Windows with asyncio")`:
  1. `tests/utils/bases/download_handlers_http.py:365-369` — `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd`.
  2. `tests/utils/bases/download_handlers_http.py:383-387` — `TestHttpBase.test_timeout_download_from_spider_server_hangs`.
  3. `tests/test_downloader_handler_twisted_ftp.py:176-180` — `TestFTP.test_invalid_credentials`.
  The first two additionally carry a `# https://twistedmatrix.com/trac/ticket/10279` comment line between the `if` guard and the `pytest.skip(...)` call; the FTP guard does not.
- **Implications**: The re-enabled coverage is three tests across two files; no other test file needs a change for the stated goal.

### How are the guarded tests collected and executed?

- **Context**: Removing a guard only matters if the test actually runs; the two HTTP tests are defined on an abstract base class.
- **Sources Consulted**: `tests/utils/bases/download_handlers_http.py` class map (`TestHttpBase`, `TestHttpsBase`, `TestHttpWithCrawlerBase`, proxy/TLS bases), `tests/test_downloader_handler_httpx.py`, `tests/test_downloader_handler_twisted_http11.py`, `tests/test_downloader_handler_twisted_http2.py`, `conftest.py`.
- **Findings**: `TestHttpBase` is declared as `class TestHttpBase(ABC)`. The concrete modules bind handler classes through mixins: `class TestHttp(HttpxDownloadHandlerMixin, TestHttpBase)` (httpx), `class TestHttp(HTTP11DownloadHandlerMixin, TestHttpBase)` (HTTP/1.1), and HTTP/2 subclasses bind `TestHttpsBase`/`TestHttpWithCrawlerBase`. The `reactor_pytest` fixture is a session-scoped pass-through of the `--reactor` command-line option (`conftest.py:119`), and `pytest_configure` selects the asyncio loop policy for `--reactor asyncio`.
- **Implications**: The execution entry points for the two re-enabled HTTP tests are the concrete downloader modules; they stay unmodified but remain the files a later verification stage must run. `TestFTP.test_invalid_credentials` is concrete and self-contained.

### Import and hygiene impact of removing the guards

- **Context**: Removing a guard can orphan an import and break lint jobs.
- **Sources Consulted**: `grep -n "sys\."` on both touched files; module import blocks.
- **Findings**: In `tests/test_downloader_handler_twisted_ftp.py`, `sys` is referenced only by the guard (line 176), so `import sys` becomes unused. In `tests/utils/bases/download_handlers_http.py`, `sys` remains referenced at lines 608, 934 and 950, so its import must stay.
- **Implications**: Exactly one import line is removed, in the FTP module.

## Design Decisions

### Decision: Keep the change confined to the two annotated test modules

- **Context**: The Detect phase must produce a bounded candidate set for a verification stage.
- **Alternatives Considered**:
  1. List every file that inherits or exercises the re-enabled tests (httpx, HTTP/1.1, HTTP/2 modules).
  2. List only the files that own the `DirtyReactorAggregateError` comments and would be modified.
- **Selected Approach**: List the two owning files as candidates, and record the inheritance chain in the reason text.
- **Rationale**: The two owning files are the ones that change; inherited tests already execute in the subclass modules and are unaffected in content, so listing them adds noise to a "candidate test files" draft without adding verification value beyond what the reason text already records.
- **Trade-offs**: A verification stage that runs node IDs directly must expand the base-class symbols into their concrete subclasses; this is documented rather than enumerated.
- **Follow-up**: If the verification stage needs runnable node IDs, expand `TestHttpBase.test_timeout_*` through the httpx and HTTP/1.1 `TestHttp`/`TestHttps` classes and the HTTP/2 `TestHttp2` class.

## Risks & Mitigations

- The skips may still be required on real Windows CI; removing them could reintroduce flaky failures — Mitigation: this is the explicit intent of the pull request ("checking if it still applies") and Requirement 3.3 accepts a surfaced failure over a silent skip.
- The guards cannot be validated on a Linux container, where `sys.platform != "win32"` — Mitigation: scope validation to static evidence (no remaining `DirtyReactorAggregateError` strings, unchanged assertions, import hygiene) instead of executing the tests.
- Inherited-test entry points could be missed by a later runner — Mitigation: the inheritance chain is recorded in `detection-draft.json` reasons and in this research log.

## Stage Boundary Note

This run covers only the cc-sdd Detect planning phases (`spec`, `detect`). No project code or test file was modified and no test was executed; the only writes are planning artifacts under `/workspace/.kiro/specs` (this feature directory plus `detection-draft.json`).

## References

- `tests/utils/bases/download_handlers_http.py` — owning module of the two HTTP timeout tests and their skip guards.
- `tests/test_downloader_handler_twisted_ftp.py` — owning module of the FTP invalid-credentials test and its skip guard.
- `conftest.py` — `--reactor` option, `reactor_pytest` fixture, `pytest_configure` loop policy.
- `https://twistedmatrix.com/trac/ticket/10279` — the dirty-reactor ticket referenced by the HTTP guards.
