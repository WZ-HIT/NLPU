# Phase 0 Research: Merge LxmlLinkExtractor Test Classes

## Decision: Use one concrete LxmlLinkExtractor test class

**Rationale**: The public package exposes `LxmlLinkExtractor` as `LinkExtractor`, while `LxmlParserLinkExtractor` remains an internal implementation detail with its own focused test class. A shared base is no longer justified because there is only one public extractor implementation to parameterize.

**Alternatives considered**:

- Keep the nested `Base.TestLinkExtractorBase` class. Rejected because it exists only to hide inherited tests and adds an unnecessary collection workaround.
- Keep `TestLxmlLinkExtractor` derived from an empty or abstract base. Rejected because it preserves indirection without adding coverage or configurability.
- Merge the LxmlParserLinkExtractor tests into the public extractor class. Rejected because those tests target a distinct internal component and are independently valuable.

## Decision: Preserve test names and assertions

**Rationale**: The PR is a structural cleanup, not a behavior change. Stable test names retain traceability in CI and reviewer diffs, while unchanged assertions keep the detection surface meaningful.

**Alternatives considered**:

- Rename or rewrite shared tests during the merge. Rejected because it expands scope and obscures the intended structural-only change.
- Remove duplicate-looking tests. Rejected because the extra cases exercise distinct filters, encodings, URL handling, or deduplication behavior.

## Decision: Keep production code untouched

**Rationale**: `LxmlLinkExtractor` remains the only public extractor, so no production behavior needs to change to support the test consolidation.

**Alternatives considered**:

- Adjust public aliases or extractor internals. Rejected because it is unrelated to the pull request and would increase compatibility risk.

## Open Questions

None. The specification and available repository evidence provide a reasonable default for every planning decision.
