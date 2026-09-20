# cc-sdd Detect stage spec

## Task under analysis

- Repository: `scrapy/scrapy`
- Base commit: `65b37286cc56b6a87c4d1eca6bdff79f658f09d2`
- Pull request: `7985` - "Rerun tests that need real Internet access when they fail"
- PR body: empty (no extra hints in `/task-input/task.md`)

## Objective of this stage

Locate the candidate test files whose tests are relevant to the PR change: the
suite that exercises real-Internet access and therefore the tests whose failure
handling the PR reworks. Nothing in the project is modified in this stage, and
no tests are executed.

## Evidence gathered from the repository (read-only)

1. `pyproject.toml` registers the marker `requires_internet: marks tests that
   need real Internet access` under `[tool.pytest.ini_options].markers`
   (line 318). At this commit nothing acts on the marker: the root
   `conftest.py` `pytest_runtest_setup` only handles `requires_reactor`,
   `only_asyncio`, `only_not_asyncio`, `requires_<optional-dep>` and
   `requires_mitmproxy`.
2. `grep -rn "requires_internet"` over the repository shows the marker is
   applied in exactly three test modules, all on a class named
   `TestRealWebsite`:
   - `tests/test_downloader_handler_httpx.py` (line 165)
   - `tests/test_downloader_handler_twisted_http11.py` (line 116)
   - `tests/test_downloader_handler_twisted_http2.py` (line 202)
3. All three classes inherit `TestRealWebsiteBase`, defined in
   `tests/utils/bases/download_handlers_http.py` (line 1516). That base holds
   the network-touching test methods - `test_download` (1549),
   `test_download_with_spider` (1557), `test_verify_certs` (1569) and
   `test_tls_logging` (1582) - which issue real requests to
   `https://books.toscrape.com/`.
4. `conftest.py` at the repository root is the pytest plugin module for this
   suite: it defines `pytest_addoption` (61), `pytest_configure` (101) and
   `pytest_runtest_setup` (110), and is where marker-driven per-test behaviour
   already lives. A rerun-on-failure behaviour for `requires_internet` tests
   belongs there as a pytest hook. No rerun mechanism exists yet at the base
   commit (`pyproject.toml`, `tox.ini` and `conftest.py` contain no
   `rerun`/`flaky`/`retry` handling and `pytest-rerunfailures` is not a
   dependency).
5. No other test module performs real-Internet requests. `books.toscrape.com`
   also appears in `tests/test_downloadermiddleware_cookies.py` (679, 745) and
   `tests/test_downloaderslotssettings.py` (29), but only as cookie-domain
   fixtures and slot keys; those tests never hit the network and are therefore
   excluded.

## Candidate selection rules used for detection

A file is a candidate when at least one of these holds:

- it contains tests marked with `requires_internet` (directly or through a
  class-level `pytestmark`), i.e. the tests whose failures the PR wants to
  retry;
- it defines the shared real-Internet test methods that those marked tests
  inherit, so the semantics of the retried tests are anchored there;
- it is the pytest plugin/hook module where per-test failure handling for the
  marker is implemented.

## Scope

In scope: locating candidate test paths, expressed as repository-relative
paths, together with the relevant symbols and a justification for each.

Out of scope: running tests, editing project code or tests, changing pytest
configuration, and any implementation of the retry behaviour.

## Deliverable

`detection-draft.json`, located in this same planning directory, containing only
a `candidates` array whose entries have `path`, `symbols` and `reason`.
