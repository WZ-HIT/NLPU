# Phase 0 Research: Fix open_in_browser base insertion without a head

## Decision: Add a headless-document fallback

**Rationale**: A browser can use a base element when a document does not provide a head element, but the current preview preparation only inserts beside an existing head. A fallback must ensure the base is effective without destroying the original body.

**Alternatives considered**:

- Parse and reserialize with a DOM parser: more correct for arbitrary HTML, but adds complexity and can rewrite unrelated markup.
- Prepend a head/base section: simple and dependency-free, but must be scoped to the HTML preview path and must preserve the existing head-insertion behavior.
- Leave headless documents unchanged: rejected because it preserves the reported bug.

## Decision: Keep insertion bounded and byte-oriented

**Rationale**: The current implementation deliberately uses bounded regular-expression searches to avoid ReDoS behavior. The fallback must not introduce an unbounded scan or repeat the head search unnecessarily.

**Alternatives considered**: A recursive or repeatedly backtracking expression, rejected because it can regress the security protections already covered by the response tests.

## Decision: Preserve current semantic checks

**Rationale**: Comments must not be treated as real head or base markup, existing base elements must not be duplicated, and text responses must remain text. The fallback should run only in the HTML/no-effective-base branch.

**Alternatives considered**: Broad document rewrites or unconditional insertion, rejected because they can change content and duplicate base elements.
