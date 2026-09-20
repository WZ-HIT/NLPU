# Quickstart Validation

1. Inspect the VCS workflow invocation in `.github/workflows/tests-vcs-deps.yml`.
2. Confirm the development dependency set in the `vcs-deps` environment in `tox.ini`.
3. Run the focused warning-sensitive tests listed in `detection-draft.json` in the normal test environment.
4. In CI, run the complete `vcs-deps` tox environment.

Expected outcome: tests pass, Scrapy-origin warnings remain actionable, and any dependency-origin suppression is narrowly scoped.

Do not run tests during planning; this guide defines validation for the implementation phase.
