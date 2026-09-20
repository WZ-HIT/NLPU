## Purpose

Define predictable process exit statuses for command-line commands when Scrapy
cannot complete crawler or spider bootstrap initialization.

## ADDED Requirements

### Requirement: Bootstrap failures produce exit code 1

When a command that starts a crawler process completes with
`bootstrap_failed` set, the command process SHALL exit with status code `1`
unless an existing command-specific failure already requires a different
non-zero status.

#### Scenario: Check encounters a bootstrap failure

- **WHEN** `scrapy check` completes with `bootstrap_failed` set
- **THEN** the process exits with status code `1`

#### Scenario: Parse encounters a bootstrap failure

- **WHEN** `scrapy parse` completes with `bootstrap_failed` set
- **THEN** the process exits with status code `1`

#### Scenario: Fetch encounters a bootstrap failure

- **WHEN** `scrapy fetch` completes with `bootstrap_failed` set
- **THEN** the process exits with status code `1`

#### Scenario: Inspecting a project that does not exist

- **WHEN** `scrapy fetch` is run outside a Scrapy project and no bootstrap
  failure occurs
- **THEN** the process preserves its existing successful exit status
