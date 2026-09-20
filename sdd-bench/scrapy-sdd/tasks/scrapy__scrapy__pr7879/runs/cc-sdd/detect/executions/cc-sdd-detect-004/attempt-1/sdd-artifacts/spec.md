# PR 7879 Planning Spec

## Source

- Repository: `scrapy/scrapy`
- Base commit: `d772acdf19251e9a03be285353b50bd1314e3d5d`
- Change: Fix `scrapy.utils.response.open_in_browser` so it adds a `<base>` tag
  when the HTML response has no `<head>` element.

## Behavioral Contract

- `open_in_browser` continues to write the response body to a temporary file
  and pass its `file://` URL to the configured open function.
- For an `HtmlResponse` without an existing real `<base>` tag, the generated
  document must contain a `<base href="<response URL>">` even when the input
  has no `<head>` element.
- Existing behavior remains intact when a real `<head>` or `<base>` is present.
- Comment-only `<head>` or `<base>` text must not be treated as a real element.

## Detection Scope

The unit-level candidate is `tests/test_utils_response.py`, which owns the
direct `open_in_browser` and base-injection assertions. The integration-level
candidate is `tests/test_commands.py`, whose `TestViewCommand` opens a
no-`<head>` HTML fixture through the `scrapy view` command.

## Constraints

- Planning only: no project code, tests, or test execution in this phase.
- All planning artifacts stay under the mounted `.kiro/specs` directory.
