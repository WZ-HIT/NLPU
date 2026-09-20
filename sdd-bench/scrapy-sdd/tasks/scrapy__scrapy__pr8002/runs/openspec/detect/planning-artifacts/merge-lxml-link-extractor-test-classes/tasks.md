## 1. Merge Test Classes

- [ ] 1.1 Move every test method from `Base.TestLinkExtractorBase` into `TestLxmlLinkExtractor` and verify the final test module contains no reference to the wrapper class.
- [ ] 1.2 Remove the `Base` wrapper and update `TestLxmlLinkExtractor` to define `extractor_cls = LxmlLinkExtractor` directly.
- [ ] 1.3 Confirm the merged class preserves all original test method names, setup behavior, and assertions.

## 2. Verify Refactor

- [ ] 2.1 Inspect `tests/test_linkextractors.py` and verify only `TestLxmlLinkExtractor` owns the merged `LxmlLinkExtractor` tests while `TestLxmlParserLinkExtractor` remains unchanged.
- [ ] 2.2 Run the `tests/test_linkextractors.py` test module in the implementation phase and verify all collected tests pass.
