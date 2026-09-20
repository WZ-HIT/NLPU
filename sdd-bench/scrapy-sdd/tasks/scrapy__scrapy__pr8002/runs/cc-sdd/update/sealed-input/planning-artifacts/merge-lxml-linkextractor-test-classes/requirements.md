# Requirements Document

## Introduction

The scrapy repository ships a single link extractor implementation
(`scrapy.linkextractors.lxmlhtml.LxmlLinkExtractor`, re-exported as
`scrapy.linkextractors.LinkExtractor`) plus its lower-level parser helper
`LxmlParserLinkExtractor`. The extractor test module
`tests/test_linkextractors.py` still carries the shape it had while more than
one link extractor implementation existed: most extractor behaviour lives in a
nested helper class, `Base.TestLinkExtractorBase`, and the only concrete
extractor class, `TestLxmlLinkExtractor`, inherits from it while overriding
`extractor_cls`.

Because only one link extractor class remains, that two-class arrangement no
longer expresses anything: the `Base` wrapper is a pytest-collection
workaround, and the inheritance indirection adds a layer that readers and
tooling must traverse to find the extractor tests. This specification covers
merging the two extractor test classes into one collected test class in
`tests/test_linkextractors.py`, without changing what is asserted.

## Boundary Context (Optional)

- **In scope**: the structure of the link extractor test module
  `tests/test_linkextractors.py` - merging `Base.TestLinkExtractorBase` and
  `TestLxmlLinkExtractor` into a single concrete test class, removing the
  now-unused `Base` collection workaround, and keeping the existing test
  cases, fixtures, assertions and test identifiers available to pytest.
- **Out of scope**: production code under `scrapy/` (including
  `scrapy/linkextractors/lxmlhtml.py`), the public `LinkExtractor` alias,
  documentation and release notes, and unrelated test modules.
- **Adjacent expectations**: `TestLxmlParserLinkExtractor` keeps covering
  `LxmlParserLinkExtractor` directly; the module keeps importing and
  exercising `LxmlLinkExtractor` and `LxmlParserLinkExtractor` the same way;
  no new runtime dependency, fixture or test-data file is introduced.

## Requirements

### Requirement 1: Single collected extractor test class

**Objective:** As a scrapy maintainer, I want the link extractor tests to live
in one collected test class, so that the test suite reflects the fact that
only one link extractor implementation exists and is easier to navigate.

#### Acceptance Criteria

1. When the test module is collected, `tests/test_linkextractors.py` shall
   expose exactly one class that tests `LxmlLinkExtractor`-level behaviour.
2. The merged extractor test class shall declare `extractor_cls` as
   `LxmlLinkExtractor` directly on the class.
3. The merged extractor test class shall define its own `setup_method` that
   builds the `linkextractor.html` `HtmlResponse` fixture used by its tests.
4. The `Base` helper class and the nested `TestLinkExtractorBase` class shall
   no longer exist in the module.
5. The merged extractor test class shall retain the name
   `TestLxmlLinkExtractor`.

### Requirement 2: Preserved test coverage and behaviour

**Objective:** As a scrapy maintainer, I want every existing link extractor
assertion to survive the merge, so that the refactor is provably
behaviour-preserving.

#### Acceptance Criteria

1. Every test method that was defined on `Base.TestLinkExtractorBase` shall
   exist on the merged extractor test class with the same name and body
   semantics.
2. Every test method that was already defined on `TestLxmlLinkExtractor`
   (including `test_canonicalize_once_per_link`, `test_link_restrict_text`,
   `test_skip_bad_links` and the three
   `test_link_allowed_is_false_*` tests) shall remain present and unchanged.
3. While the merged class runs, the shared `extractor_cls()` construction and
   the `<a>`/`<area>` parsing fixtures shall behave exactly as before the
   merge.
4. The module shall remain runnable as a standalone pytest target, with the
   same test count as before the merge.

### Requirement 3: Parser helper tests remain independent

**Objective:** As a scrapy maintainer, I want the `LxmlParserLinkExtractor`
tests untouched, so that the merge does not silently widen scope.

#### Acceptance Criteria

1. `TestLxmlParserLinkExtractor` shall remain a separate class in the module.
2. The tests `test_extract_links`, `test_deduplicates_by_canonical_url` and
   `test_strip_false` shall keep instantiating `LxmlParserLinkExtractor`
   directly and keep their current assertions.

### Requirement 4: No production or unrelated test changes

**Objective:** As a scrapy reviewer, I want the change confined to test
organisation, so that the refactor carries no runtime risk.

#### Acceptance Criteria

1. The change shall not modify any file under `scrapy/`.
2. The change shall not modify any other file under `tests/`.
3. The change shall not add, remove or rename test-data fixtures used by the
   module.
