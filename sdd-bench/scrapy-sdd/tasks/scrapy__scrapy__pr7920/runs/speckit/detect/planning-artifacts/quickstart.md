# Quickstart Validation

## Prerequisites

Use a Scrapy project that can intentionally trigger a crawler bootstrap failure.

## Validation Scenarios

1. Run `scrapy check` in the failure fixture and confirm status `1`.
2. Run `scrapy parse <url>` in the failure fixture and confirm status `1`.
3. Run `scrapy fetch <url>` in the failure fixture and confirm status `1`.
4. Run each command through its existing successful scenario and confirm status `0`.
5. Run an invalid-arguments scenario and confirm status `2`.

The command-level contract is recorded in
[contracts/command-exit-codes.md](contracts/command-exit-codes.md). This document is a
validation guide only; test implementation belongs in `tasks.md`.
