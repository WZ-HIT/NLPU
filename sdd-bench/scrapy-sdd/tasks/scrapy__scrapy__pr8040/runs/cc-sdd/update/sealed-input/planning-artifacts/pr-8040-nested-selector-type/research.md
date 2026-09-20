# Research & Design Decisions

## Summary

- **Feature**: `pr-8040-nested-selector-type`
- **Discovery Scope**: Extension (defect fix in an existing wrapper module)
- **Key Findings**:
  - `Selector.__init__` forces `type="html"` when `response is None`, which is exactly the
    case for nested selectors created inside parsel.
  - parsel `xpath` propagates `type=_xml_or_html(self.type)` to nested selectors, but
    `jmespath` propagates only `root=`, so its nested type comes from `_get_root_type`.
  - `jmespath` requires `self.type in {"html", "xml"}` for non-JSON selectors and reads
    `self.root.text`; a `dict` root mis-typed as HTML therefore fails on chaining.
  - All selector flavor/type assertions in the test suite live in `tests/test_selector.py`;
    response-level selector assertions live in `tests/test_http_response_text.py`.

## Research Log

### Selector type normalization

- **Context**: Determine where a wrong type for nested selectors can originate.
- **Sources Consulted**: `scrapy/selector/unified.py`, installed `parsel/selector.py`
  (`_get_root_type`, `_get_root_and_type_from_text`, `Selector.jmespath`, `Selector.xpath`).
- **Findings**: With `type=None` and `response=None`, Scrapy overwrites parsel's
  determination with `"html"`. For `text=` inputs it also upgrades plain text to HTML
  before parsel sees it.
- **Implications**: Removing the `response is None` branch restores parsel's ownership of
  flavor detection while keeping explicit `"xml"`/`"json"`/`"html"` mappings for Scrapy
  response classes.

### Test surface discovery

- **Context**: Find the smallest credible verification surface without running tests.
- **Sources Consulted**: `tests/test_selector.py`, `tests/test_http_response_text.py`,
  `tests/utils/bases/http_response.py`, `tests/test_loader.py`, `tests_typing/`.
- **Findings**: `tests/test_selector.py` holds `TestSelector.test_flavor_detection*` and
  `TestJMESPath` (nested `jmespath`/`css`/`xpath` chaining, including `json` in `html`).
  `tests/test_http_response_text.py` asserts `response.selector.type` and selector
  shortcuts on `TextResponse` subclasses, including `JsonResponse` behavior.
- **Implications**: `tests/test_selector.py` is the primary candidate;
  `tests/test_http_response_text.py` is a secondary, lower-confidence candidate.

## Risks & Mitigations

- Risk: The exact upstream fix may differ in shape from the inferred minimal change.
  Mitigation: the candidate files assert observable selector behavior, independent of the
  internal implementation choice.
- Risk: Relying on nested `jmespath` only. Mitigation: candidates also cover `css`/`xpath`
  chaining and explicit response-class types.

## References

- `scrapy/selector/unified.py` — Scrapy `Selector` / `SelectorList` wrappers.
- `parsel/selector.py` — flavor detection and nested selector construction.
- `docs/topics/selectors.rst` — user-facing selector documentation.
