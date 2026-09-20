## Purpose

Defines how Scrapy's PyPy test environments collect code coverage so that the
PyPy CI job stays fast while the CPython jobs keep reporting complete coverage
to Codecov.

## ADDED Requirements

### Requirement: PyPy environments do not instrument subprocesses

The PyPy test environments SHALL NOT measure coverage inside the subprocesses
spawned by the test suite. Coverage measured in the main test process MAY be
kept, and MUST be kept if it is still uploaded and compared with the CPython
coverage reports.

#### Scenario: Subprocess-heavy tests run on PyPy

- **WHEN** the PyPy test environment runs a test that spawns a subprocess
- **THEN** the spawned process runs without coverage measurement and its
  runtime is close to the runtime of the same test without coverage enabled

#### Scenario: PyPy coverage data is still reported

- **WHEN** the PyPy environment finishes its test run
- **THEN** any coverage data it still produces is reported in the same way as
  before this change

### Requirement: CPython environments keep subprocess coverage

The CPython test environments SHALL continue to measure coverage in
subprocesses so that removing it for PyPy does not create coverage gaps on
Codecov.

#### Scenario: CPython coverage job

- **WHEN** a CPython test environment with coverage enabled runs tests that
  spawn subprocesses
- **THEN** coverage data from those subprocesses is still collected and
  uploaded
