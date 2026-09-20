## 1. Preparation

- [ ] 1.1 Re-read `scrapy/utils/response.py` and
      `tests/test_utils_response.py`, then confirm the reported bug by writing a
      headless `HtmlResponse` (`<html><body><p>hi</p></body></html>`) through
      `open_in_browser()` with a capturing `_openfunc`; verify the captured file
      contains no `<base>` element.
- [ ] 1.2 Identify every caller of `open_in_browser()` (`scrapy/commands/view.py`,
      `scrapy/shell.py`, docs) and verify none of them depends on the current
      no-head behavior of the generated file.

## 2. Implementation

- [ ] 2.1 In `scrapy/utils/response.py`, extract the base-tag injection into a
      private helper (for example `_add_base_tag(body: bytes, url: str) -> bytes`)
      that keeps today's behavior: it returns the body unchanged when a base tag
      exists outside comments, and otherwise inserts the tag at the start of the
      real `<head>` element; verify `tests/test_utils_response.py` still passes
      unchanged for the existing cases.
- [ ] 2.2 Extend that helper with the fallback for bodies whose comment-stripped
      markup has no `<head>` element: insert
      `<head><base href="<response url>"></head>` immediately after the
      `<html …>` open tag when present, otherwise at the start of the body;
      verify the headless body from 1.1 now yields exactly one base tag inside a
      `<head>` element.
- [ ] 2.3 Ensure the new patterns stay linear
      (`<head(?:[^<>]*?)>` / `<html(?:[^<>]*?)>`, no nested quantifiers) and
      verify the input from `test_open_in_browser_redos_head`
      (`b"<head\t" * 80_000`) plus a large headless body are still handled well
      below the 0.2 s CPU budget.

## 3. Tests

- [ ] 3.1 Add cases to `tests/test_utils_response.py` asserting a base tag is
      injected for headless HTML, e.g. a new parameter in `test_inject_base_url`
      with `<html><body>Hello world.</body></html>` and a dedicated
      `test_open_in_browser_injects_base_without_head` test; verify both fail
      against the unmodified implementation and pass with the fix.
- [ ] 3.2 Add a case for markup with no `<html>` and no `<head>` element
      (fragment body) asserting the base tag is injected and the original
      markup is preserved verbatim apart from the injected tag.
- [ ] 3.3 Run `pytest tests/test_utils_response.py` and verify the whole file
      passes, including the existing comment-handling and ReDoS regression
      tests.

## 4. Documentation

- [ ] 4.1 Add a bug-fix entry to the unreleased section of `docs/news.rst`
      describing that `open_in_browser()` now adds a base tag when the response
      has no `<head>` element, referencing `:gh:`6550``; verify the file
      renders as valid reStructuredText.

## 5. Verification

- [ ] 5.1 Run `pytest tests/test_utils_response.py -q` and
      `python -m pytest tests/test_command_shell.py -q` and verify no
      regressions in the code paths that call `open_in_browser()`.
- [ ] 5.2 Run `openspec validate fix-open-in-browser-base-without-head --strict`
      and verify the change artifacts are valid.
