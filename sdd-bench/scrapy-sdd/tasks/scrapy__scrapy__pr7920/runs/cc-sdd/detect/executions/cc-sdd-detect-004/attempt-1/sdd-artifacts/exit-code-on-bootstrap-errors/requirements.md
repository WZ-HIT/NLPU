# Requirements: Exit code 1 on crawler bootstrap errors

## Context

PR scrapy/scrapy#7920 resolves scrapy/scrapy#4292. `scrapy crawl` and
`scrapy runspider` already map an early ("bootstrap") crawler failure to exit
code 1, but `check`, `parse` and `fetch` still exit 0 when the crawl never
really started.

## Requirements

### Requirement 1: check reports bootstrap failures

When the contract crawl behind `scrapy check` fails to bootstrap (for example a
spider whose start machinery raises), the command must exit with code 1.

**Acceptance criteria**

1. When `scrapy check` cannot reach a successful crawl, its process exit code
   is 1.
2. Contract test failures keep behaving as before (exit code 1).
3. A fully successful check run still exits with code 0.

### Requirement 2: parse reports bootstrap failures

When `scrapy parse` cannot resolve a usable spider or the crawl bootstrap
fails, the command must exit with code 1.

**Acceptance criteria**

1. A parse run whose crawler bootstrap failed exits with code 1.
2. Successful parse runs continue to exit with code 0.

### Requirement 3: fetch reports bootstrap failures

When the crawl bootstrap for `scrapy fetch` fails, the command must exit with
code 1.

**Acceptance criteria**

1. A fetch run whose crawler bootstrap failed exits with code 1.
2. Successful fetch runs continue to exit with code 0.

### Requirement 4: no behavioural regressions

1. Usage errors keep exiting with code 2.
2. Existing command behaviour (output, logging, contract summaries) is
   unchanged apart from the exit code.
