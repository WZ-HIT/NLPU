## Why

Scrapy already exercises Python 3.15 in the scheduled VCS-dependency job, but
the main Linux, macOS, and checks pipelines stop at 3.14. Adding 3.15 to those
pipelines gives compatibility failures a first-class signal before the release
branch depends on them.

## What Changes

- Add Python 3.15 to the Linux, macOS, and checks CI matrices, enabling
  prerelease interpreters where the workflow uses `actions/setup-python`.
- Extend the tox Python environment list with `py315`.
- Advertise Python 3.15 in the package classifiers.
- Keep Windows out of the 3.15 matrix because its dependency set is blocked by
  lxml, as noted in the pull request.
- Use the existing `tests/test_utils_misc/__init__.py` coverage of
  `scrapy.utils.misc.walk_modules_iter` as the focused compatibility signal for
  the Python 3.15 import traversal behavior named in the task.

## Capabilities

### New Capabilities

- `python-ci-coverage`: The supported Python versions exercised by continuous
  integration and declared by package metadata.

### Modified Capabilities

None. Repository-level OpenSpec specifications do not exist yet, so this
capability is introduced as a new contract.

## Impact

Affected files are `.github/workflows/tests-ubuntu.yml`,
`.github/workflows/tests-macos.yml`, `.github/workflows/checks.yml`,
`tox.ini`, and `pyproject.toml`. No runtime API or dependency change is
expected. Windows CI remains on its current Python matrix until lxml supports
3.15 there.
