# Test-only maintenance task

Repository: `scrapy/scrapy`

Investigate tests that are disabled because of `DirtyReactorAggregateError`
workarounds and update the tests where repository evidence shows that the
workarounds may no longer apply.

## Constraints

- Infer the relevant files and test cases by inspecting the base repository.
- Modify files only beneath the repository-root `test/` or `tests/` directories.
- Do not modify production code.
- Do not access Git remotes, future commits, pull-request patches, merged code,
  gold tests, or reference answers.
- Preserve useful setup and established Scrapy test conventions.
- Use the SDD workflow selected by the experiment launcher.
- Do not run tests during the current output-only experiment; leave validation
  for the post-run human review stage.

## Bounded repository research

- Start with one exact search for `DirtyReactorAggregateError` beneath `tests/`.
- After locating matches, inspect only the matching code ranges, their directly
  used fixtures or decorators, and the minimum relevant dependency/configuration
  lines.
- Do not repeat equivalent searches with synonyms once the scope is known.
- Do not enumerate the whole repository, read complete CI workflow collections,
  or inspect complete third-party package source trees.
- Limit command output to the smallest useful range and never intentionally emit
  more than 200 lines from one repository-research command.
- Reuse findings written by an earlier SDD phase instead of rediscovering them.
