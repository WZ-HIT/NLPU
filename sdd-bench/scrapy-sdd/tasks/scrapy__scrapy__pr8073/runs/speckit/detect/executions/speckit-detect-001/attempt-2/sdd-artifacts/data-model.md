# Data Model

## Candidate

**Fields**

- `path`: Repository-relative path to a test file under `tests/`.
- `symbols`: Qualified test symbols associated with the affected skip.
- `reason`: Concise evidence explaining why the file and symbols are candidates.

## Relationships

A candidate contains one or more test symbols. Multiple candidates may share a
common historical issue, but each file is represented once.

## Validation Rules

- `path` must be non-empty, repository-relative, and begin with `tests/`.
- `symbols` must be a non-empty array of strings.
- Each symbol must correspond to code in the referenced file.
- `reason` must mention the `DirtyReactorAggregateError` skip or its review.
- The detection draft must contain no top-level keys other than `candidates`.
