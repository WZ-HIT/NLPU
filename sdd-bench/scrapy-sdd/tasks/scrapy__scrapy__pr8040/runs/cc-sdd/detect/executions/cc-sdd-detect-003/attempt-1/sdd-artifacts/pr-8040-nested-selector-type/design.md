# Design Document

## Overview

The Detect stage only plans where the change is verified; it does not implement it. This
design records the defect mechanism, the contract Scrapy has with parsel, and the test
surface that can exercise it.

**Purpose**: identify the smallest credible set of test files that cover selector type
resolution and nested selector construction for the PR 8040 change.

## Boundary Commitments

### This Spec Owns

- The analysis of how `scrapy.selector.unified.Selector` maps responses to parsel types.
- The candidate test file list for verification (`detection-draft.json`).

### Out of Boundary

- The production fix itself.
- Writing or editing tests.
- Executing the test suite (explicitly forbidden in this stage).

### Allowed Dependencies

- Read-only inspection of `/workspace/scrapy/**` and `/workspace/tests/**`.
- Installed `parsel` sources for understanding nested selector construction.

### Revalidation Triggers

- The set of response classes handled by `Selector.__init__` changes.
- parsel changes how nested selectors propagate `type`.

## Architecture

### Existing Architecture Analysis

`scrapy/selector/unified.py` defines `Selector` and `SelectorList` as thin subclasses of
the parsel equivalents. `Selector.__init__` normalizes `type` before delegating to
`parsel.Selector.__init__`:

```python
if type is None:
    if isinstance(response, XmlResponse):
        type = "xml"
    elif isinstance(response, JsonResponse):
        type = "json"
    elif response is None or isinstance(response, HtmlResponse):
        type = "html"
```

parsel constructs nested selectors internally. For `xpath` results it passes an explicit
`type=_xml_or_html(self.type)`; for `jmespath` results it passes only `root=` (no `type`).
`parsel.Selector.__init__` then derives the type via `_get_root_type(root, input_type=None)`,
which returns `"json"` for `dict` / `list` / valid-JSON roots and `"html"` otherwise.

### Architecture Pattern & Boundary Map

**Architecture Integration**:
- Selected pattern: delegation — Scrapy maps response classes to types, parsel owns flavor
  detection for everything else.
- Boundary: `scrapy.selector.unified` must not override parsel's root-based detection.

### Technology Stack

| Layer | Choice / Version | Role in Feature | Notes |
|-------|------------------|-----------------|-------|
| Selector wrapper | `scrapy.selector.unified` | Maps responses to parsel types | Change site |
| Parsing/selection | `parsel` (>= 1.8 for JSON) | Owns flavor detection and nested selector creation | Dependency |
| Responses | `scrapy.http` | Provide `HtmlResponse`/`XmlResponse`/`JsonResponse`/`TextResponse` | Type inputs |

## File Structure Plan

### Directory Structure

```
.kiro/specs/
├── detection-draft.json                  # Detect phase output (single file)
└── pr-8040-nested-selector-type/         # Spec phase artifacts
    ├── spec.json
    ├── requirements.md
    ├── design.md
    ├── tasks.md
    └── research.md
```

### Modified Files

None. The Detect stage is read-only with respect to production code and tests.

## Requirements Traceability

| Requirement | Summary | Components | Interfaces | Flows |
|-------------|---------|------------|------------|-------|
| 1.1 | Delegate nested type to parsel | `Selector.__init__` | parsel `Selector.__init__` | Construct nested selector |
| 1.2-1.4 | Keep explicit response-class types | `Selector.__init__` | `scrapy.http` responses | Selector construction |
| 1.5 | Chained selection on JSON roots | `Selector`, `SelectorList` | `jmespath`/`css`/`xpath` | Nested selection |
| 1.6 | Plain-text responses stay unset | `Selector.__init__` | `TextResponse` | Type detection |
| 2.1-2.3 | Candidate discovery output | detection draft | JSON contract | Detect phase |

## Testing Strategy

This stage does not run tests. The verification surface identified for the update stage is:

- Unit tests: `tests/test_selector.py` — `TestSelector.test_flavor_detection*` assert
  `Selector.type` for XML/HTML/JSON/text; `TestJMESPath` covers nested `jmespath`, `css`,
  and `xpath` chaining on JSON payloads.
- Integration-style response tests: `tests/test_http_response_text.py` — `test_selector`,
  `test_selector_shortcuts`, and `test_json_response*` assert selector flavor and chaining
  on `TextResponse` subclasses.
