## Purpose

Defines what `scrapy.utils.response.open_in_browser()` must write to the local
file it asks the browser to open, so that a crawled HTML page keeps working
offline with its relative links, images and stylesheets.

## ADDED Requirements

### Requirement: Base tag is injected for HTML responses without a head element

When `open_in_browser()` handles an HTML response whose body contains no
`<head>` element, it SHALL still write a `<base href="<response url>">` element
into the file that it passes to the browser, so relative URLs resolve against
the crawled page. It SHALL do so by introducing a `<head>` element that can
legitimately hold the base tag, rather than by emitting a bare `<base>` element
in the document body.

#### Scenario: HTML document with no head element

- **WHEN** `open_in_browser()` is called with an `HtmlResponse` whose body is
  `<html><body><p>Hello world.</p></body></html>`
- **THEN** the file written for the browser contains exactly one
  `<base href="<response url>">` element
- **AND** that base element is located inside a `<head>` element

#### Scenario: HTML document that is not wrapped in html or head elements

- **WHEN** `open_in_browser()` is called with an `HtmlResponse` whose body has
  no `<html>` and no `<head>` element, for example
  `<p>Hello world.</p>`
- **THEN** the file written for the browser contains a
  `<base href="<response url>">` element
- **AND** the response markup itself is preserved

### Requirement: Existing base tags are respected

`open_in_browser()` SHALL NOT add a second base tag when the response body
already declares one in real markup, and SHALL keep the injected base tag as
the first child of the existing `<head>` element when a `<head>` element is
present. Base tags that appear only inside HTML comments SHALL NOT be treated
as existing base tags.

#### Scenario: Response already declares a base tag

- **WHEN** `open_in_browser()` is called with an `HtmlResponse` whose real
  markup already contains `<base href="http://real.com">`
- **THEN** the file written for the browser still contains
  `<base href="http://real.com">`
- **AND** it does not contain a second `<base>` element pointing at the
  response URL

#### Scenario: Base tag only appears inside a comment

- **WHEN** the response body contains `<!-- <base href='http://other.com'> -->`
  and no real base tag
- **THEN** the file written for the browser contains a
  `<base href="<response url>">` element

#### Scenario: Commented out head element

- **WHEN** the response body contains a commented out `<head>` element before
  the real `<head>` element
- **THEN** the injected `<base href="<response url>">` element is placed inside
  the real `<head>` element

### Requirement: Body content and non-HTML handling are unchanged

`open_in_browser()` SHALL preserve HTML comments and all other response markup
while injecting the base tag, SHALL continue to write text responses to a file
with a `.txt` extension, and SHALL continue to raise `TypeError` for response
types that are neither HTML nor text.

#### Scenario: HTML comments are preserved

- **WHEN** the response body contains an HTML comment next to the markup where
  the base tag is injected
- **THEN** the comment is still present in the file written for the browser

#### Scenario: Text response uses a text file extension

- **WHEN** `open_in_browser()` is called with a `TextResponse` that is not an
  HTML response
- **THEN** the URL passed to the browser ends with `.txt`

#### Scenario: Unsupported response type

- **WHEN** `open_in_browser()` is called with a plain `Response`
- **THEN** it raises `TypeError`
