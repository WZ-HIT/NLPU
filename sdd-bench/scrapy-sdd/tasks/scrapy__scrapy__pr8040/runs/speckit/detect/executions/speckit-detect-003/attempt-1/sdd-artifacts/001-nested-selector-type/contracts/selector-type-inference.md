# Selector Type Inference Contract

## Preconditions

- A selector constructor may receive a response, text, body, or an existing root.
- An explicit type takes precedence.

## Behavior

1. When a supported response is supplied without a root or explicit type, the existing response-class default is applied.
2. When text is supplied without an explicit type, the existing top-level text behavior is preserved.
3. When an existing root is supplied without an explicit type, Scrapy leaves the type unset so parsel can infer it.
4. Nested values returned by parsel retain the inferred JSON, HTML, XML, or text representation.

## Invariants

- No response, loader, or extraction API changes.
- No new dependency or public parameter is introduced.
- Existing explicit-type behavior is unchanged.
