# Implementation Plan

- [ ] 1. Remove the DirtyReactorAggregateError guard from the FTP test module
  - Delete the `if reactor_pytest == "asyncio" and sys.platform == "win32": pytest.skip("This test produces DirtyReactorAggregateError on Windows with asyncio")` block at the top of `TestFTP.test_invalid_credentials` in `tests/test_downloader_handler_twisted_ftp.py`.
  - Remove the module-level `import sys`, which after the deletion has no remaining reference in this file.
  - Observable completion: the module no longer contains a `DirtyReactorAggregateError` string and imports without an unused `sys`.
  - _Requirements: 2.1, 2.2, 4.1, 4.3_
  - _Boundary: tests/test_downloader_handler_twisted_ftp.py_

- [ ] 2. Remove the two DirtyReactorAggregateError guards from the HTTP handler base module
  - Delete the two guards (and their `# https://twistedmatrix.com/trac/ticket/10279` comments) at the top of `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd` and `TestHttpBase.test_timeout_download_from_spider_server_hangs` in `tests/utils/bases/download_handlers_http.py`.
  - Keep the module's `sys` import and all other guards untouched, since `sys.platform` and `sys.version_info` are still used elsewhere in the file.
  - Observable completion: the file contains no `DirtyReactorAggregateError` string while lines 608, 934 and 950 still reference `sys`.
  - _Requirements: 1.1, 1.2, 3.2, 4.2_
  - _Boundary: tests/utils/bases/download_handlers_http.py_

- [ ] 3. Verify the re-enabled coverage and the untouched configurations
  - Confirm by static inspection that the three tests (`TestFTP.test_invalid_credentials`, `TestHttpBase.test_timeout_download_from_spider_nodata_rcvd`, `TestHttpBase.test_timeout_download_from_spider_server_hangs`) no longer contain any skip path, and that their assertions (`ConnectionLost`, `DownloadTimeoutError`) are unchanged.
  - Confirm that collection entry points for the base-class tests remain `tests/test_downloader_handler_httpx.py`, `tests/test_downloader_handler_twisted_http11.py` and `tests/test_downloader_handler_twisted_http2.py`, none of which is edited.
  - Observable completion: a repository-wide search for `DirtyReactorAggregateError` returns no hits, and each re-enabled symbol is listed in the Detect draft with its owning file.
  - _Requirements: 1.3, 2.3, 3.1, 3.3_
  - _Depends: 1, 2_
