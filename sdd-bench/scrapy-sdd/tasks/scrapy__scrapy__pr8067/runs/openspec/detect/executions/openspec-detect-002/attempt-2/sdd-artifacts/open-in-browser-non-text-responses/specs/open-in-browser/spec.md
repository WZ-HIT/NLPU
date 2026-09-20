## Purpose

Lets developers open any response that Scrapy fetched, including non-text payloads such as
images and PDFs, in a local web browser for inspection.

## ADDED Requirements

### Requirement: Non-text responses are opened using their Content-Type media type

`open_in_browser()` SHALL accept any `Response`, including responses whose body is not text.
For responses that are neither HTML nor text responses, it SHALL choose the suffix of the
temporary file from the media type of the response `Content-Type` header (`image/png` → `.png`,
`application/pdf` → `.pdf`). Media type parameters such as `charset` SHALL be ignored and the
media type SHALL be matched case-insensitively. The response body SHALL be written to the file
byte for byte, and the function SHALL pass the resulting `file://` URL to its open function and
return that function's result.

#### Scenario: Binary image response

- **WHEN** `open_in_browser()` is called with a `Response` whose `Content-Type` is `image/png`
- **THEN** the open function receives a `file://` URL whose path ends in `.png`
- **AND** the file content equals the response body

#### Scenario: Media type with parameters and unusual casing

- **WHEN** the response `Content-Type` is `Application/PDF; charset=binary`
- **THEN** the file passed to the open function has the `.pdf` suffix

#### Scenario: Missing or unknown media type

- **WHEN** the `Content-Type` header is absent or its media type is not recognized
- **THEN** the body is written with a generic `.bin` suffix and the response is opened, rather
  than raising `TypeError`

### Requirement: HTML and text response behavior is preserved

`open_in_browser()` SHALL keep its current behavior for HTML and other text responses. For an
`HtmlResponse` it SHALL inject a `base` tag built from the response URL (after the doctype
declaration when one is present, and only when the existing body does not already provide one
that takes precedence) and write the body with the `.html` suffix. For any other `TextResponse`
it SHALL write the body with the `.txt` suffix.

#### Scenario: HTML response keeps base injection and html suffix

- **WHEN** `open_in_browser()` is called with an `HtmlResponse`
- **THEN** the file passed to the open function has the `.html` suffix and its content contains
  exactly one `base` tag pointing at the response URL

#### Scenario: Non-HTML text response uses the txt suffix

- **WHEN** `open_in_browser()` is called with a `TextResponse` that is not an `HtmlResponse`
- **THEN** the file passed to the open function has the `.txt` suffix

### Requirement: The scrapy view command opens non-text responses

The `scrapy view` command SHALL open any fetched response in a browser, including responses whose
body is not text, and SHALL NOT report "Cannot view a non-text response." or exit with an error
because of the response media type.

#### Scenario: Viewing an image URL

- **WHEN** `scrapy view` is run for a URL that Scrapy downloads as a non-text response
- **THEN** the command exits with status 0
- **AND** the browser recorded a `file://` URL whose content equals the fetched body
