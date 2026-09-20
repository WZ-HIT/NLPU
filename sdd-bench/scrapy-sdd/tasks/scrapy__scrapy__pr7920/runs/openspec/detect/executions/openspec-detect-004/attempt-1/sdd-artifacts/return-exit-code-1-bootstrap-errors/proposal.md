## Why

The `check`, `parse`, and `fetch` commands can finish with a non-zero
`CrawlerProcess.bootstrap_failed` state while still exiting with status `0`.
Automation therefore treats failed spider/bootstrap initialization as success,
even though `crawl` and `runspider` already report the same condition as exit
code `1`.

## What Changes

- Make `check`, `parse`, and `fetch` set their command exit code to `1` after
  the crawler process finishes when bootstrap failed.
- Preserve existing success and normal command-error exit codes.
- Add command-level regression coverage for each affected command.

## Capabilities

### New Capabilities

- `cli-bootstrap-exit-code`: Defines the process exit-code behavior of Scrapy
  commands when crawler or spider bootstrap initialization fails.

### Modified Capabilities

<!-- None: openspec/specs currently contains no established capabilities. -->

## Impact

- Affected commands: `scrapy/commands/check.py`, `scrapy/commands/parse.py`,
  and `scrapy/commands/fetch.py`.
- Affected behavior: shell/CI callers can rely on a non-zero exit status when
  these commands encounter crawler bootstrap failures.
- Tests: command-level tests for `check`, `parse`, and `fetch` need regression
  cases for bootstrap failure.
