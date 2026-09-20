# Phase 1 Data Model: Typed Spider Test Modules

This feature deals with source artifacts, not persisted data. The entities below describe the
planning/detection vocabulary used by the specification, plan, tasks, and the detect-phase output.

## In-scope test module

| Field | Type | Notes |
|-------|------|-------|
| path | repository-relative path | e.g. `tests/test_spider_crawl.py` |
| kind | `test-module` \| `test-helper` | helpers hold fixtures/base classes rather than collected tests |
| subject | `spider` \| `crawl-spider` \| `sitemap-spider` \| `spider-middleware` \| `shared` | spider relation |
| collected | boolean | whether pytest collects tests directly from the file |

**Relationships**: an in-scope test module may import one or more in-scope test helpers; the shared
base class (`tests/utils/bases/spider.py`) is subclassed by three in-scope test modules.

**Validation rules**: path must exist in the repository and be spider-related (FR-008); no
non-spider module may appear in scope.

## Annotation target

| Field | Type | Notes |
|-------|------|-------|
| module | path | owning in-scope module |
| symbol | qualified name | function, method, fixture, or attribute |
| parameters | list of (name, annotation) | `self`/`cls` excluded |
| returns | annotation | must be present unless a documented suppression applies |
| suppression | optional string | inline ignore/cast justification |

**State transitions**: `unannotated → annotated`; `annotated → excluded-from-body-check` is forbidden
once the module leaves the exclusion list.

## Static-analysis exclusion entry

| Field | Type | Notes |
|-------|------|-------|
| module | dotted module path | e.g. `tests.test_spider_sitemap` |
| setting | `check_untyped_defs = false` | the exemption being removed |
| removed | boolean | true for every in-scope module after the change |

**Validation rules**: an entry may be removed only if the module contains no annotation target
without an annotation or documented suppression (FR-003).

## Detection candidate (detect-phase artifact)

| Field | Type | Notes |
|-------|------|-------|
| path | string | repository-relative test path (must be under `tests/`) |
| symbols | array of strings | relevant symbols in that file |
| reason | string | why the file is a candidate for this change |

**Validation rules**: the artifact contains exactly one `candidates` array and nothing else; every
`path` is repository-relative; no candidate lies outside the test tree. The machine-readable schema
is `contracts/detection-draft.schema.json`.
