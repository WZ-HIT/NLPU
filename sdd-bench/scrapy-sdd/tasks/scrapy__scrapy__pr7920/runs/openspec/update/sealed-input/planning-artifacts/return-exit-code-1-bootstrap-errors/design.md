## Context

`CrawlerRunnerBase` records failed crawler or spider initialization in the
public `bootstrap_failed` flag. `crawl` and `runspider` inspect that flag after
`CrawlerProcess.start()` and set `exitcode` to `1`. The `check`, `parse`, and
`fetch` commands also start a crawler process but do not inspect the flag.
See `proposal.md` for the motivation.

## Goals / Non-Goals

**Goals:**

- Report bootstrap failures through the existing command exit-code mechanism.
- Cover all three commands with command-level regression tests.

**Non-Goals:**

- Change how bootstrap errors are detected or logged.
- Change exit codes for usage errors, normal crawls, or contract failures.

## Decisions

- Inspect `self.crawler_process.bootstrap_failed` immediately after
  `start()` in each affected command and set `self.exitcode = 1` when true.
  This matches the established `crawl` and `runspider` pattern and preserves
  command-specific exit-code handling, such as failed contracts in `check`.
- Keep the logic in each command rather than in `cmdline.execute()`.
  Centralizing it would introduce a broad behavior change for every command,
  including commands that may intentionally manage bootstrap failures.

## Risks / Trade-offs

- A command may set a different non-zero exit code before the bootstrap
  check. The commands affected here only use `0` or `1`, so assigning `1`
  does not erase a distinct status.
- Bootstrap failures may already emit errors. The additional exit code does
  not change logging and only affects process status.
