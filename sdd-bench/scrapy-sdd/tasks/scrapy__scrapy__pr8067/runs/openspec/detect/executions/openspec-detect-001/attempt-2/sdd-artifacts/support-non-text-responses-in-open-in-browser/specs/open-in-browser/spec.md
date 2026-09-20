## Purpose

Define how Scrapy opens downloaded responses in a local browser while preserving response metadata needed by the browser.

## ADDED Requirements

### Requirement: Content-Type determines the browser file extension
For responses that are not HTML responses, the browser-opening utility SHALL
select a temporary-file extension from the response `Content-Type` media type.
Text responses without a more specific known extension SHALL continue to use
the `.txt` extension. Unsupported responses SHALL still raise a clear error.

#### Scenario: Non-text response with a known content type
- **WHEN** a non-HTML response has a `Content-Type` of `image/png`
- **THEN** the browser-opening utility opens a temporary file whose path ends in `.png`

#### Scenario: Text response without a specific extension
- **WHEN** a text response has no `Content-Type` that maps to a known extension
- **THEN** the browser-opening utility opens a temporary file whose path ends in `.txt`

#### Scenario: Response without usable content type information
- **WHEN** a response has neither an HTML response type nor a usable `Content-Type`
- **THEN** the browser-opening utility raises a `TypeError`

### Requirement: View command supports non-text responses
The `scrapy view` command SHALL pass non-text responses to the browser-opening
utility instead of rejecting them solely because they are not text responses.

#### Scenario: Viewing an image response
- **WHEN** a user runs `scrapy view` for a URL whose response is an image
- **THEN** the command exits successfully and opens the downloaded content in the browser

