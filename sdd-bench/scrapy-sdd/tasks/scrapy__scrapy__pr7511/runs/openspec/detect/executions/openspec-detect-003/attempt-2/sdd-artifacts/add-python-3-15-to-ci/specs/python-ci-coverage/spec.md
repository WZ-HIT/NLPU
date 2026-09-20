## Purpose

Define the Python interpreter versions that Scrapy's continuous integration
and published package metadata present as supported.

## ADDED Requirements

### Requirement: CI exercises Python 3.15 where dependencies permit

The project SHALL run its primary test matrix on Python 3.15 on Linux and
macOS, and SHALL allow prerelease interpreters when selecting that version.

#### Scenario: Prerelease Python is selected

- **WHEN** a Python 3.15 CI job configures `actions/setup-python`
- **THEN** the job SHALL allow prerelease versions so the 3.15 interpreter can
  be installed

#### Scenario: Platform dependency blocks Python 3.15

- **WHEN** a platform dependency such as lxml cannot be installed on Python
  3.15
- **THEN** that platform MAY remain on its existing supported Python matrix
  while the remaining platforms exercise 3.15

### Requirement: Project tooling accepts Python 3.15

The project SHALL expose a tox environment for Python 3.15 and SHALL declare
Python 3.15 in its package classifiers.

#### Scenario: Python 3.15 environment is selected

- **WHEN** a developer or CI job requests the `py315` tox environment
- **THEN** tox SHALL recognize the environment as part of the configured Python
  environment list

#### Scenario: Package metadata is inspected

- **WHEN** build metadata for Scrapy is inspected
- **THEN** it SHALL include the Python 3.15 programming-language classifier
