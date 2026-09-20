## 1. API Surface

- [ ] 1.1 Move the handler module to
  `scrapy/core/downloader/handlers/_http2.py` and the supporting package to
  `scrapy/core/_http2/`, then verify the old source paths are absent.
- [ ] 1.2 Update production imports and qualified references to the private
  paths, then verify `python -c "from scrapy.core.downloader.handlers._http2
  import H2DownloadHandler"` succeeds.
- [ ] 1.3 Confirm the handler lifecycle and behavior are unchanged by inspecting
  the moved code and verifying the focused handler tests still exercise the same
  methods.

## 2. Documentation

- [ ] 2.1 Remove the experimental warning and present the handler as supported
  in `docs/topics/download-handlers.rst`; verify the rendered section has no
  experimental warning.
- [ ] 2.2 Update current handler path references and `DOWNLOAD_HANDLERS`
  examples in current docs; verify every current example imports the private
  path while historical release notes remain unchanged.
- [ ] 2.3 Search current documentation for `handlers.http2.H2DownloadHandler`
  and `scrapy.core.http2`; verify only historical release notes retain old paths.

## 3. Tests

- [ ] 3.1 Update `tests/test_downloader_handler_twisted_http2.py` imports,
  `DOWNLOAD_HANDLERS` paths, docstrings, and symbol references; verify the file
  collects successfully with the project's reactor test configuration.
- [ ] 3.2 Update `tests/test_http2_client_protocol.py` imports and patch/logger
  targets to `scrapy.core._http2`; verify the protocol test module collects
  successfully.
- [ ] 3.3 Add or adjust a focused assertion that the supported handler is
  loadable through its new documented path; verify the assertion passes and the
  existing plain-HTTP rejection assertion still passes.

## 4. Validation

- [ ] 4.1 Search for remaining current references to the old public path;
  verify only historical release notes retain them.
- [ ] 4.2 Run `tests/test_downloader_handler_twisted_http2.py` and
  `tests/test_http2_client_protocol.py`; verify both pass in an environment with
  Twisted HTTP/2 support.
- [ ] 4.3 Run the documentation build or the project's docs reference checks;
  verify there are no broken current API references.
