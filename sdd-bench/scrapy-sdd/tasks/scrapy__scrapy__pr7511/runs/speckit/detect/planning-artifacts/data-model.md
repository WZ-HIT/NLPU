# Data Model: Python 3.15 CI Compatibility

This feature does not introduce persistent application data. The planning model below describes configuration and validation entities only.

## CI Matrix Entry

**Purpose**: Describes one test configuration in a GitHub Actions workflow.

**Fields**:

- `runner`: Operating system used by the job.
- `python_version`: Interpreter version, including prerelease status when applicable.
- `tox_environment`: Tox environment selected for the job.
- `coverage`: Whether coverage output is uploaded.
- `exclusion_reason`: Optional explanation when a platform is intentionally absent.

**Validation rules**:

- Python 3.15 entries must enable prerelease installation.
- Existing supported-version entries must remain present.
- Every intentional platform exclusion must have a repository-visible reason.

## Compatibility-Sensitive Operation

**Purpose**: Represents behavior that must remain stable across interpreter versions.

**Fields**:

- `name`: `scrapy.utils.misc.walk_modules_iter`.
- `observable_contract`: Yield the requested module and discoverable submodules.
- `error_contract`: Surface import failures when the generator is consumed.
- `consumers`: Command discovery and spider discovery.

**Validation rules**:

- Normal package and nested-package traversal must remain unchanged.
- Missing-module errors must remain deferred until iteration.
- Import-time errors from discovered modules must still propagate.

## Candidate Test

**Purpose**: Identifies a test location that can validate the compatibility-sensitive operation.

**Fields**:

- `path`: Repository-relative test path.
- `symbols`: Relevant test symbols within the file.
- `reason`: Why the test is connected to the changed behavior.

**Relationships**:

- A compatibility-sensitive operation has one or more candidate direct or indirect tests.
- A CI matrix entry validates a cross-section of candidate tests when its tox environment runs.
