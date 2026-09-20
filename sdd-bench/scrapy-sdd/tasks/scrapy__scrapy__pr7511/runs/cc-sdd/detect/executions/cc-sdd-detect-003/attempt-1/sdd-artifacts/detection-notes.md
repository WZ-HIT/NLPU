# Detect planning notes — scrapy/scrapy PR 7511

## Inputs

- Repository: `scrapy/scrapy`
- Pull request: `7511` — "Add Python 3.15 to CI."
- Base commit: `1420418c813ed01af78da62bc4a6e60bb4a7403b`
- PR body checklist item under detection:
  `scrapy/utils/misc.py::scrapy.utils.misc.walk_modules_iter`
- Scope limits: planning only. No project code or tests were modified, and no
  tests were run.

## Spec phase

Goal of the detect stage: from the PR description and the base tree, locate the
repository-relative test files that would verify or need updating for this
change.

Situation in the base tree:

- `pyproject.toml` classifiers and `.github/workflows/*` cover Python 3.10–3.14;
  `tests-vcs-deps.yml` already pins a prerelease 3.15 for source builds. Adding
  3.15 to CI (including `tox.ini` `envlist = py{310,...,314}`) is the nominal PR
  change.
- The only source-level item called out by the PR is
  `scrapy/utils/misc.py::walk_modules_iter`. That function imports a package and
  its submodules with `pkgutil.iter_modules`; it is Python-version sensitive
  (deprecations of `pkgutil`/`iter_modules`, egg/zipimport and namespace-package
  handling), which is why it needs attention when a new interpreter is added to
  CI.
- `pyproject.toml` sets `filterwarnings = ["error", ...]`, so a new
  `DeprecationWarning` raised by the module walk turns into a test failure in
  whatever test exercises the symbol.

Detection target: test files that execute `scrapy.utils.misc.walk_modules_iter`
(directly or through its consumers) or that pin
`scrapy.utils.misc` version-sensitive behavior.

## Detect phase

Evidence gathered (read-only):

- `grep -rn "walk_modules" tests docs scrapy` — direct test usage exists only in
  `tests/test_utils_misc/__init__.py` (`test_walk_modules`,
  `test_walk_modules_egg`); production callers are `scrapy/cmdline.py`
  (`_iter_command_classes`) and `scrapy/spiderloader.py`
  (`SpiderLoader._load_all_spiders`); docs references are `docs/news.rst`.
- `tests/test_utils_misc/` is the test package for `scrapy/utils/misc.py` and
  also holds `test_return_with_argument_inside_generator.py` (AST-based,
  version-sensitive `is_generator_with_return_value`) and the walked fixtures
  in `tests/test_utils_misc/test_walk_modules/` plus the `test.egg` asset.
- Indirect coverage of the symbol was mapped through its only two production
  callers: `tests/test_spiderloader/__init__.py` (spider module loading, broken
  module handling) and `tests/test_commands.py` (in-process
  `scrapy.cmdline.execute`, command discovery via `COMMANDS_MODULE`).

Ranking used: direct unit tests of the named symbol first, then the two indirect
consumer test modules, then the sibling `scrapy.utils.misc` test module.

## Output

- `detection-draft.json` — the single detection draft, containing only the
  `candidates` array with `path`, `symbols` and `reason` per candidate.
- This notes file — the spec/detect planning artifact. Both files live in the
  mounted method planning directory (`.kiro/specs`); nothing else was written
  and no project code or tests were touched.
