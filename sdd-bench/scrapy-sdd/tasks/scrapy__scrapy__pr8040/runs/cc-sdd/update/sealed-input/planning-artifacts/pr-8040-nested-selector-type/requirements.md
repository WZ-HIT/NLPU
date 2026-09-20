# Requirements Document

## Introduction

This spec covers the change proposed by `scrapy/scrapy` pull request 8040 ("Let parsel
determine the type of nested selectors"), which resolves issue 8038. It is produced by
the spec phase of the cc-sdd Detect stage; only planning artifacts are in scope, and no
production code or test code is modified.

The observed defect is that `scrapy.selector.unified.Selector` forces `type="html"` for
responses other than `XmlResponse` and `JsonResponse` **and** whenever no response is
given. Nested selectors produced by parsel are constructed with `root=...` and no
response, so they inherit the forced `"html"` type instead of the type parsel derives
from the root object. The proposed fix is to stop forcing `"html"` when no response is
available and let parsel determine the type.

## Boundary Context (Optional)

- **In scope**: locating the test files that can verify nested-selector type handling for
  `scrapy.selector.Selector` / `SelectorList` and the `css`, `xpath`, and `jmespath`
  chaining paths that construct nested selectors.
- **Out of scope**: editing `scrapy/selector/unified.py` or any other production module;
  editing test files; running the test suite.
- **Adjacent expectations**: parsel (`parsel.Selector`) owns flavor detection; Scrapy only
  maps Scrapy response classes to explicit parsel types.

## Requirements

### Requirement 1: Nested selector type delegation

**Objective:** As a Scrapy user, I want nested selectors to derive their type from parsel,
so that chained selection on non-HTML content (for example JSON) keeps working.

#### Acceptance Criteria

1. When `Selector` is constructed with no `response` (nested selector creation, `type=None`),
   the selector shall pass `type=None` to `parsel.Selector` so parsel derives the type from
   the root node or text.
2. When `Selector` is constructed from an `HtmlResponse`, the selector type shall remain
   `"html"`.
3. When `Selector` is constructed from an `XmlResponse`, the selector type shall remain
   `"xml"`.
4. When `Selector` is constructed from a `JsonResponse`, the selector type shall remain
   `"json"`.
5. When a selector derived from a `JsonResponse` produces a non-string nested result
   (for example `response.jmespath("a")` where `a` is an object), the nested selector shall
   report the parsel-derived type and further chaining (`jmespath`, `css`, `xpath`) shall
   not raise.
6. When a selector is constructed from any other `TextResponse` subclass, the type shall
   be left unset so parsel determines it from the response body.

### Requirement 2: Regression coverage discovery

**Objective:** As a maintainer, I want the existing test surface for selector flavor
detection identified, so that the change can be verified without inventing new modules.

#### Acceptance Criteria

1. The detection phase shall identify the test files that assert `Selector.type` and that
   exercise nested (`jmespath`/`css`/`xpath`) selector chaining.
2. The detection phase shall record each candidate as a repository-relative path with the
   relevant symbols and a concrete reason.
3. The detection phase shall not execute tests and shall not modify project code or tests.
