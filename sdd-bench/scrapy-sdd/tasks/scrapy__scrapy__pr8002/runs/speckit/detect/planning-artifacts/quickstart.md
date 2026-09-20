# Phase 1 Quickstart: Merge LxmlLinkExtractor Test Classes

## Prerequisites

- The repository test dependencies are installed.
- The working tree contains the planned consolidation in `tests/test_linkextractors.py`.

Planning performed no test execution and made no project-code or test changes.

## Validation Scenarios

### 1. Confirm test discovery

Run pytest collection for the targeted module and confirm that the consolidated LxmlLinkExtractor class is discovered while the hidden base class is no longer needed.

```bash
pytest --collect-only tests/test_linkextractors.py
```

Expected outcome: The collected LxmlLinkExtractor tests are present under one class, and no tests are missing because of inheritance or pytest-name masking.

### 2. Run the targeted behavior suite

```bash
pytest tests/test_linkextractors.py
```

Expected outcome: All existing link extractor tests pass, including conditional skips already encoded in the suite.

### 3. Inspect the structural diff

Review the diff for `tests/test_linkextractors.py` and confirm that it only moves or removes test-suite indirection. No production file should appear in the diff, and the 3 LxmlParserLinkExtractor tests should remain separate.
