# Phase 0 Research: Typed Spider Test Modules

## Decision: Scope selection — the spider cluster of the static-analysis exclusion list

**Decision**: Primary scope is the spider-related cluster currently exempted from untyped-definition
body checking: `tests/spiders.py`, `tests/utils/bases/spider.py`, `tests/test_spider.py`,
`tests/test_spider_crawl.py`, `tests/test_spider_sitemap.py`,
`tests/test_spidermiddleware_output_chain.py`, `tests/test_spidermiddleware_process_start.py`.

**Rationale**: These modules are all spider-related, are all still excluded in `pyproject.toml`, and
form a coherent work unit: the spider fixtures (`tests/spiders.py`), the shared spider test base
class (`tests/utils/bases/spider.py`), the three modules that subclass that base, and the two
spider-middleware test modules. Modules that already pass strict checking (for example
`tests/test_crawl.py` and `tests/test_spiderstate.py`) are out of scope.

**Alternatives considered**: (a) annotating every unannotated test module in one change — rejected as
unreviewable; (b) restricting to `tests/test_spider*.py` only — rejected because the fixtures and
base class must be annotated for their consumers to check cleanly.

## Decision: Annotation syntax and imports

**Decision**: Use postponed annotations at module level, PEP 585 built-in generics and PEP 604
unions (`list[str]`, `Spider | None`), and import runtime-only types under a type-checking guard.

**Rationale**: Matches the style already used by annotated parts of the suite and satisfies the
project's lint rules for postponed annotations and type-checking-only imports.

**Alternatives considered**: legacy `Optional[...]`/`List[...]` syntax — rejected (project style is
modern syntax); runtime imports of typing-only types — rejected because they add test-time imports.

## Decision: Handling un-annotatable constructs

**Decision**: For deferred-returning fixtures, dynamically constructed spider classes, monkeypatched
callables, and intentionally-invalid calls, use the narrowest accurate annotation plus an inline
suppression/cast where required, keeping an explanatory context.

**Rationale**: Widening annotations to `Any` would defeat FR-001's intent, while rewriting tests
would violate FR-004/SC-004.

**Alternatives considered**: keeping per-module exclusions for problematic lines — rejected because
whole-module exclusions are exactly what this feature removes.

## Decision: Verification evidence

**Decision**: Evidence = strict type checking of the repository with the in-scope exclusion entries
removed, a run of the affected test modules showing an identical set of collected test identifiers
and outcomes, and lint/format checks on the changed files.

**Rationale**: Directly measures SC-001, SC-003, and FR-005 while keeping the diff annotation-only.

**Alternatives considered**: coverage comparison — rejected as unrelated to the annotation contract.

## Open items

None. All technical unknowns were resolvable from the repository (no `[NEEDS CLARIFICATION]` markers
remain in `spec.md`).
