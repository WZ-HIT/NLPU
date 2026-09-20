# Command Exit-Code Contract

## Scope

`scrapy check`, `scrapy parse`, and `scrapy fetch`.

## Contract

| Condition | Exit status |
| --- | --- |
| Command completes successfully | `0` |
| Crawler bootstrap fails | `1` |
| Command-line usage is invalid | `2` |

## Invariants

- Exit status is emitted after command execution.
- A bootstrap failure cannot result in status `0` for the affected commands.
- Existing successful and usage-error behavior is unchanged.
