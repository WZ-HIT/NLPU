## Purpose

Define consistent selector-type behavior for selectors created from responses,
text, and nested values so that XPath, CSS, and JMESPath operations behave
according to the underlying data type.

## ADDED Requirements

### Requirement: Nested selector types are determined by parsel

When a selector is created with a nested `root` value and no explicit type,
Scrapy SHALL leave type determination to parsel. Selectors created directly
from a response or text without a `root` SHALL continue to use Scrapy's
response- and text-based type inference.

#### Scenario: Scalar JSON result produces a JSON selector

- **WHEN** a non-string scalar is selected from a JSON selector
- **THEN** the resulting nested selector has type `"json"`
- **AND** `get()` returns the scalar value

#### Scenario: Response selector inference is unchanged

- **WHEN** a selector is created directly from an HTML, XML, or JSON response
- **THEN** its type is `"html"`, `"xml"`, or `"json"` respectively

#### Scenario: Explicit type is preserved

- **WHEN** a selector is created with an explicit `type` value
- **THEN** that type is passed to parsel unchanged
