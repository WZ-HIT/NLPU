# Data Model: Address VCS workflow warnings

No persistent entities or state transitions are introduced.

## Conceptual Entities

- **Warning observation**: category, message, source, and whether it originates in Scrapy or a dependency.
- **Candidate test**: repository-relative test path, relevant symbols, and reason for selection.
- **Validation run**: the `vcs-deps` environment invocation and its warning-sensitive tests.

## Validation Rules

- Every candidate path must be an existing repository test path.
- Every warning must have an identified origin before it is handled.
- Suppressions must be no broader than the observed warning.
