## Context

Scrapy's selector constructor currently infers a type from the response or text
whenever no explicit type is supplied. Nested selectors can instead pass a
`root` value, for which parsel has its own type-detection logic. See
`proposal.md` for the user-visible problem.

## Goals / Non-Goals

**Goals:**

- Delegate nested-root type detection to parsel.
- Preserve Scrapy's existing response- and text-based inference.
- Avoid changing public APIs or explicit type handling.

**Non-Goals:**

- Changing parsel's type-detection algorithm.
- Changing selector extraction semantics for HTML, XML, or response selectors.

## Decisions

- Gate Scrapy's inference on `root is _NOT_SET`. This is the smallest change
  that distinguishes direct response/text construction from nested-root
  construction while still forwarding an explicit type unchanged.
- Keep `_response_from_text()` and response-derived `base_url` behavior as-is.
  The change only affects which selector type reaches parsel.

## Risks / Trade-offs

- Nested-root values whose type parsel cannot infer may still fall back to
  parsel's JSON default. Mitigation: cover representative non-string JSON
  values and retain existing response-selector tests.
- Passing a nested root with an explicit incompatible type can still raise the
  same errors raised by parsel. Mitigation: do not alter explicit type values.
