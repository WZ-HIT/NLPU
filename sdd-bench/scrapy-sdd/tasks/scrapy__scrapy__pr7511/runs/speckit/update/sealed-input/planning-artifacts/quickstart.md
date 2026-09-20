# Quickstart Validation: Python 3.15 CI Compatibility

This guide describes validation to perform during implementation. No commands here were executed during the planning-only phase.

## Prerequisites

- Repository dependencies installed according to `pyproject.toml` and `tox.ini`.
- A Python 3.15 prerelease interpreter available through the project's environment tooling.
- A supported Linux environment for the first full CI-compatible validation.

## Targeted Module-Walker Validation

Run the direct module-walker tests under the supported development interpreter:

```bash
python -m pytest tests/test_utils_misc/__init__.py -q
```

Expected outcome:

- Regular packages and nested packages are discovered.
- A single-module path yields only that module.
- Egg-backed discovery still finds the expected modules.
- Missing-module errors are deferred until generator consumption.

## Consumer Regression Validation

Run the command and spider-loading consumers:

```bash
python -m pytest tests/test_spiderloader/__init__.py tests/test_commands.py -q
```

Expected outcome:

- Spider modules are recursively discovered with unchanged error and warning behavior.
- Built-in and project command modules remain discoverable.
- Existing duplicate-name handling remains unchanged.

## Python 3.15 Validation

Run the selected tox environment with Python 3.15 once the interpreter is installed:

```bash
tox -e py -- tests/test_utils_misc/__init__.py
```

Expected outcome:

- The interpreter is recognized as Python 3.15.
- The direct module-walker tests pass.
- No compatibility shim is needed beyond the narrowly scoped production change.

## CI Validation

Open or update the pull request and inspect the Python 3.15 matrix job for the supported runner.

Expected outcome:

- Python 3.15 prerelease installation succeeds.
- The selected dependency environment installs.
- The configured tests run rather than being skipped.
- Existing Python 3.10 through 3.14 jobs remain present.

## Failure Triage

- Dependency installation failure: document the dependency and platform, then keep the unsupported matrix entry out until it can run.
- Module-discovery failure: reduce it to the direct module-walker tests before changing production behavior.
- Consumer-only failure: inspect command or spider-loader assumptions without changing the public discovery contract.
