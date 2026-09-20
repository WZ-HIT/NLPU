# Research: Address VCS workflow warnings

## Decision

Use focused warning filters or dependency-compatibility changes only where the warning source and lifetime are understood. Keep global warning policy unchanged.

## Rationale

The VCS workflow intentionally tests unreleased dependencies. Blanket filters would hide regressions in Scrapy, while changing unrelated production code solely to silence third-party warnings would broaden risk.

## Alternatives Considered

- Ignore all warnings: rejected because it hides actionable failures.
- Pin every development dependency: rejected because it defeats the workflow's purpose.
- Remove warning-sensitive tests: rejected because it reduces behavioral coverage.

## Evidence

The workflow runs `TOXENV=vcs-deps` with `pytest -n auto --no-cov --timeout=120`. The `vcs-deps` tox environment installs current development revisions listed in `tox.ini`; warning-sensitive tests are primarily those that explicitly capture, filter, or assert warnings.
