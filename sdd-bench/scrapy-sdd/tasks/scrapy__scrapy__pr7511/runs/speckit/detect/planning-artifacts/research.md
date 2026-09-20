# Phase 0 Research: Python 3.15 CI Compatibility

## Decision: Request prerelease interpreters explicitly in CI

**Rationale**: GitHub's Python setup action does not select prerelease interpreters by default. A Python 3.15 matrix entry therefore needs prerelease installation enabled, and the resulting job must remain distinguishable from stable-interpreter coverage.

**Alternatives considered**:

- Let the action resolve the latest stable interpreter: rejected because it would not test Python 3.15.
- Install Python 3.15 manually in every job: rejected because the repository already uses `actions/setup-python`.

## Decision: Start with a constrained dependency environment

**Rationale**: Python 3.15 coverage depends on interpreter wheels and source builds for the full dependency stack. A constrained environment such as VCS dependencies or a focused tox environment can expose interpreter incompatibilities before every platform and optional dependency path is ready.

**Alternatives considered**:

- Add Python 3.15 to every platform and tox environment immediately: rejected while platform dependencies such as lxml may not support the prerelease.
- Skip Python 3.15 until all optional dependencies support it: rejected because it delays detection of stdlib and runtime incompatibilities.

## Decision: Keep Windows exclusion explicit while lxml support is unavailable

**Rationale**: The PR context identifies Windows as dependency-blocked by lxml. An explicit omission or documented exclusion is preferable to a silently failing or automatically skipped job.

**Alternatives considered**:

- Add Windows 3.15 and accept a known failure: rejected because it would make CI status misleading.
- Remove Windows coverage entirely: rejected because existing supported-version coverage must remain.

## Decision: Treat `walk_modules_iter` as the compatibility-sensitive behavior

**Rationale**: The PR explicitly identifies `scrapy/utils/misc.py::scrapy.utils.misc.walk_modules_iter`. Its observable contract is module discovery through `import_module` and recursive `pkgutil.iter_modules` traversal, with deferred import errors because the function is a generator.

**Alternatives considered**:

- Assume only CI configuration changed: rejected because the PR body calls out a runtime function.
- Replace module discovery wholesale: rejected because the existing contract and consumers are broader than the reported incompatibility.

## Decision: Validate the narrow contract first, then consumers

**Rationale**: Direct tests in `tests/test_utils_misc/__init__.py` cover regular packages, nested packages, single modules, missing modules, deprecation behavior, and egg-backed modules. Consumer suites for spider loading and command loading exercise real recursive discovery paths.

**Alternatives considered**:

- Run only the direct unit test: rejected because real consumers provide integration coverage.
- Run the entire suite first: rejected for local diagnosis because it is slower and less informative; full CI remains the final gate.

## Open Questions

None. Platform exclusions are treated as dependency constraints and must be documented in CI configuration rather than treated as unresolved product questions.
