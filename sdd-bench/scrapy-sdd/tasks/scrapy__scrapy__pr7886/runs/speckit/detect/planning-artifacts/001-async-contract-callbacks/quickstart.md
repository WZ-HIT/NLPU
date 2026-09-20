# Quickstart Validation: Asynchronous Callbacks in Spider Contracts

## Prerequisites

- A working development checkout of the repository at the feature branch.
- The project's test dependencies installed (`pytest`, `pytest-twisted`).
- No new settings or dependencies are required for this feature.

## Scenario 1 - Coroutine callback passes its contract (US1)

1. Create a spider module with an asynchronous callback:

   ```python
   import scrapy

   class AsyncSpider(scrapy.Spider):
       name = "async_spider"
       start_urls = ["data:,"]

       async def parse(self, response):
           """
           @url data:,
           @returns items 1 1
           """
           return {"url": response.url}
   ```

2. Run `scrapy check async_spider` in that project.
3. Expected: the contract passes, the summary reports success/`OK`, and the process
   exits with status `0`.
4. Negative control: change `@returns items 2 2`, rerun, and confirm a contract
   failure with a non-zero exit status (no "async callbacks" error).

## Scenario 2 - Async generator callback passes its contract (US2)

1. Replace the callback body with `yield {"url": response.url}` inside
   `async def parse(...)`, keeping `@returns items 1 1`.
2. Run `scrapy check async_spider`; expect success and exit status `0`.
3. Weaken/strengthen the `@returns` range and confirm the failure message names the
   expected range.

## Scenario 3 - Custom contract hooks around async callbacks (US3)

1. Define a custom contract with a `pre_process` that raises `AssertionError`, apply
   it to an asynchronous callback, and run `scrapy check`.
2. Expected: a failure attributed to the `[async_spider] parse (<name> pre-hook)` test
   case. Repeat with a raising `post_process` and expect an error.

## Focused automated checks (do not run as part of planning)

- `pytest tests/test_contracts.py` - unit coverage of hook/result handling.
- `pytest tests/test_command_check.py` - `scrapy check` command and exit status.
- `pytest tests/test_utils_spider.py` - `iterate_spider_output()` normalization used by
  the contract path.

## References

- [spec.md](./spec.md) - requirements and acceptance scenarios.
- [plan.md](./plan.md) - technical context and file layout.
- [contracts/contract-hooks.md](./contracts/contract-hooks.md) - hook interface details.
- [data-model.md](./data-model.md) - result shapes and outcome mapping.
