# Requirements Document

## Project Description (Input)

Scrapy users who inspect responses outside the text-response hierarchy need
`scrapy.utils.response.open_in_browser` to open those responses instead of
rejecting them. The PR adds Content-Type-based handling so non-text responses,
including those viewed through the `scrapy view` command, can be written to a
temporary file with an appropriate extension and opened in the browser.

## Requirements

1. `open_in_browser` shall accept non-`TextResponse` `Response` instances.
2. `open_in_browser` shall derive a file extension from the response
   `Content-Type` when the response is not an HTML or text response.
3. `open_in_browser` shall preserve existing HTML base-tag injection and
   existing text-response `.txt` behavior.
4. The `scrapy view` command shall pass non-text responses to
   `open_in_browser` instead of logging "Cannot view a non-text response."
5. Existing behavior for unsupported or missing response metadata shall remain
   deterministic and covered by tests.
