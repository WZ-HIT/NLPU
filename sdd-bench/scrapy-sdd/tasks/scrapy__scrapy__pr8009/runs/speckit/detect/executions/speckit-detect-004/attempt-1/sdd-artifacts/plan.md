# Implementation Plan: Mandatory zstd decompression

**Branch**: `8009-mandatory-zstd` | **Date**: 2026-09-20 | **Spec**: [spec.md](spec.md)

**Input**: PR 8009, "Use compression.zstd/backports.zstd and make zstd support mandatory"

## Summary

Replace optional `zstandard` support with the standard-library
`compression.zstd` module on Python 3.14+ and the mandatory `backports.zstd`
package on older Python versions. Advertise and decode zstd unconditionally,
while preserving the existing bounded-decompression behavior.

## Technical Context

**Language/Version**: Python >=3.10

**Primary Dependencies**: `backports-zstd>=1.3.0; python_version < '3.14'`;
standard-library `compression.zstd` on Python >=3.14

**Storage**: N/A

**Testing**: pytest (planning only; not executed in this task)

**Target Platform**: Cross-platform Python library

**Project Type**: Library and command-line framework

**Performance Goals**: Preserve chunked decompression and avoid unbounded
output while enforcing the configured maximum size.

**Constraints**: Do not modify code or tests; do not run tests. Detection
artifacts must stay under the mounted planning directory.

**Scale/Scope**: Dependency metadata, compression utility import/decode path,
HTTP compression middleware behavior, documentation, and affected tests.

## Constitution Check

The project constitution is still an unratified template, so it defines no
additional gates. The plan preserves the repository's existing compatibility,
testing, and safety expectations.

## Project Structure

### Documentation (this feature)

```text
specs/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
└── detection-draft.json
```

No `contracts/` directory is needed because this change introduces no new
external interface.

### Source Code (repository root)

```text
scrapy/
├── downloadermiddlewares/
│   └── httpcompression.py
└── utils/
    └── _compression.py

tests/
└── test_downloadermiddleware_httpcompression.py

pyproject.toml
tox.ini
docs/
└── intro/
    └── install.rst
```

**Structure Decision**: Keep the existing single-package layout. Change the
compression utility and middleware in place, update dependency metadata, and
adapt the existing middleware test module.

## Complexity Tracking

No constitution violations or complexity exceptions are required.
