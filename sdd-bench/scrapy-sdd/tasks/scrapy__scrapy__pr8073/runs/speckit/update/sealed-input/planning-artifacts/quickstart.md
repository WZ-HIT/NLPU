# Quickstart: Re-enable DirtyReactorAggregateError Tests

## Prerequisites

- A supported Scrapy development environment.
- The repository's normal pytest and pytest-twisted dependencies.
- A Windows environment with the asyncio reactor for validating the original skip path.

## Validation Scenarios

1. Run the FTP invalid-credentials test on Windows with the asyncio reactor. Confirm it is
   collected and executed, not skipped, and that it expects `ConnectionLost`.
2. Run the HTTP no-data timeout test through an HTTP download-handler test class on Windows
   with the asyncio reactor. Confirm it is collected and executed, not skipped, and expects
   `DownloadTimeoutError`.
3. Run the HTTP hanging-response timeout test through an HTTP download-handler test class on
   Windows with the asyncio reactor. Confirm it is collected and executed, not skipped, and
   expects `DownloadTimeoutError`.
4. Run the affected modules under the repository's regular reactor matrix to check for
   regressions.

This planning stage does not execute tests; the commands belong to the later implementation
and validation stage.
