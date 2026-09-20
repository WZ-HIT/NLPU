## 1. Extension resolution

- [ ] 1.1 Change `open_in_browser()` in `scrapy/utils/response.py` to accept any `Response` and accept `TextResponse` type hints accordingly, verified by the module's mypy/pyright checks passing
- [ ] 1.2 Resolve the temporary file suffix for non-HTML, non-text responses from the `Content-Type` media type with `mimetypes.guess_extension()`, ignoring parameters and casing, and fall back to `.bin` when the media type cannot be resolved; verify with unit tests for `image/png`, `application/pdf; charset=binary`, and a header-less `Response`
- [ ] 1.3 Keep the existing `HtmlResponse` (`base` tag injection, `.html`) and `TextResponse` (`.txt`) branches unchanged, verified by the existing tests in `tests/test_utils_response.py` passing

## 2. Command behavior

- [ ] 2.1 Remove the `TextResponse` guard and the "Cannot view a non-text response." message from `scrapy/commands/view.py`, verified by `TestViewCommand` in `tests/test_commands.py` passing
- [ ] 2.2 Update `TestViewCommand.test_non_text_response` so it asserts that a non-text URL is opened in the browser (recording browser receives a `file://` URL whose content equals the fetched body) instead of asserting the removed message

## 3. Tests

- [ ] 3.1 Add unit tests in `tests/test_utils_response.py` covering the suffix chosen for a non-text response with a known media type and for a response without a usable `Content-Type`; verify the new tests fail before 1.2 and pass after it
- [ ] 3.2 Adjust `tests/test_utils_response.py` assertions that expect `TypeError` for a plain `Response` so they reflect the new behavior; verify the whole file passes

## 4. Documentation

- [ ] 4.1 Update the `open_in_browser()` docstring plus `docs/topics/debug.rst`, `docs/topics/shell.rst`, and the `view` command section of `docs/topics/commands.rst` to describe Content-Type-based suffixes and that non-text responses are supported; verify with a docs build
- [ ] 4.2 Add a release note entry in `docs/news.rst` mentioning the behavior change and issue #3902

## 5. Verification

- [ ] 5.1 Run `pytest tests/test_utils_response.py tests/test_commands.py -k "browser or view"` and confirm it passes
- [ ] 5.2 Manually run `scrapy view` against the mock server image URL and confirm the recorded browser URL ends in `.png`
