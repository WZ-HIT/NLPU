# Implementation Plan: Rerun Internet-Dependent Test Failures

**Date**: 2026-09-20 | **Spec**: `/workspace/specs/spec.md`

## Summary

Configure pytest so tests marked `requires_internet` are rerun after failure, without retrying unrelated tests or masking permanent failures.

## Technical Context

**Language/Version**: Python 3.10-3.14

**Primary Dependencies**: pytest and its CI plugins

**Storage**: N/A

**Testing**: pytest marker `requires_internet`

**Target Platform**: Scrapy CI on Linux, macOS, and Windows

**Project Type**: Python library

**Constraints**: Preserve final failure status and leave non-marked tests unchanged

**Scale/Scope**: Three concrete test modules currently carrying `requires_internet`

## Constitution Check

The constitution is an unfilled template with no enforceable gates. This is a test-only change and does not alter library behavior.

## Project Structure

### Documentation

```text
/workspace/specs/spec.md
/workspace/specs/plan.md
/workspace/specs/tasks.md
/workspace/specs/detection-draft.json
```

### Relevant Repository Paths

```text
tests/test_downloader_handler_twisted_http11.py
tests/test_downloader_handler_twisted_http2.py
tests/test_downloader_handler_httpx.py
tests/utils/bases/download_handlers_http.py
pyproject.toml
tox.ini
```

**Structure Decision**: The feature affects pytest configuration and the three concrete `TestRealWebsite` classes carrying `requires_internet`.

## Complexity Tracking

No constitution violations.
