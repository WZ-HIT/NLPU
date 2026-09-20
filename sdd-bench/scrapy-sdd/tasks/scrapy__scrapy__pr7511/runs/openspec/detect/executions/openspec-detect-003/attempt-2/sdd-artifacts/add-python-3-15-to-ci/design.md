## Context

See `proposal.md` for motivation. The current Linux, macOS, and checks
workflows top out at Python 3.14, while the scheduled VCS-dependency workflow
already asks for Python 3.15 with `allow-prereleases: true`. The project's tox
environment list and package classifiers also stop at 3.14. The
`walk_modules_iter` symbol named by the task is directly exercised by
`tests/test_utils_misc/__init__.py`.

## Goals / Non-Goals

**Goals:**

- Make Python 3.15 a visible CI target on platforms whose dependencies permit
  it.
- Keep the version matrix, tox environment names, and package metadata
  consistent.
- Preserve the existing 3.14 jobs, including coverage ownership.

**Non-Goals:**

- Adding Windows Python 3.15 coverage while lxml is unavailable there.
- Changing the minimum supported Python version.
- Refactoring `walk_modules_iter` unless a Python 3.15 failure demonstrates
  that a compatibility change is required.

## Decisions

- Use `allow-prereleases: true` on the affected setup-python steps because
  Python 3.15 may still be a prerelease in the CI environment. The alternative
  is to wait for a final release, which would hide compatibility failures for
  longer.
- Add 3.15 as an additional matrix entry instead of replacing the 3.14
  coverage jobs. This keeps existing coverage behavior stable while adding a
  new compatibility signal.
- Extend the existing `py{310,311,312,313,314}` pattern to include `315`
  rather than introducing a separate tox configuration. The alternative adds
  duplicate configuration without changing behavior.
- Keep Windows unchanged because the task explicitly identifies lxml as its
  blocker.

## Risks / Trade-offs

- [Python 3.15 packages may be unavailable] -> Let failing dependency jobs
  report the concrete blocker, and keep platform-specific exclusions explicit
  rather than masking failures.
- [Prerelease CI can be unstable] -> Keep the 3.14 jobs as the stable coverage
  baseline and isolate 3.15 as an additive signal.
- [A compatibility failure appears outside `walk_modules_iter`] -> Report the
  failing test and resolve it in the implementation phase rather than widening
  the planning scope with speculative changes.
