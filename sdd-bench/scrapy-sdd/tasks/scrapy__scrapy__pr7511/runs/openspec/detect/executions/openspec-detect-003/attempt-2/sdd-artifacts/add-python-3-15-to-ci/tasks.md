## 1. Python 3.15 Configuration

- [ ] 1.1 Add the Python 3.15 classifier to `pyproject.toml` and include
  `315` in the tox Python environment list; verify the `py315` environment is
  recognized by tox configuration parsing.
- [ ] 1.2 Add Python 3.15 matrix entries to the Linux and macOS test workflows
  and the checks workflow where the selected tooling supports it; enable
  prerelease handling in each affected setup-python step; verify the workflow
  files parse and the resulting matrix contains 3.15 on the intended
  platforms.
- [ ] 1.3 Confirm Windows remains unchanged because lxml blocks Python 3.15;
  verify the Windows matrix still contains only its currently supported
  versions.

## 2. Focused Compatibility Verification

- [ ] 2.1 Run the focused candidate
  `tests/test_utils_misc/__init__.py::test_walk_modules` under the configured
  Python 3.15 environment and verify `walk_modules_iter` discovers package and
  leaf modules and propagates import failures.
- [ ] 2.2 Run the focused candidate
  `tests/test_utils_misc/__init__.py::test_walk_modules_egg` under Python 3.15
  and verify traversal through the fixture egg remains correct.
- [ ] 2.3 Run the Python 3.15 CI-equivalent test environment and verify the
  task completes without regressions; if `walk_modules_iter` fails, make the
  smallest compatibility change and rerun the focused candidates.

## 3. Final Validation

- [ ] 3.1 Run the project checks affected by the changed configuration and
  verify they pass.
- [ ] 3.2 Inspect the final CI matrix and package metadata and verify Python
  3.15 is reported consistently on supported platforms.
