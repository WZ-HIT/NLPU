# Data Model: Bootstrap Error Exit Codes

This change introduces no persistent entities.

## Runtime State

### CrawlerProcess

- `bootstrap_failed`: Boolean flag indicating that crawler startup failed.

### ScrapyCommand

- `exitcode`: Integer process status returned by the command-line entry point. The required
  transition is `0 -> 1` after command execution when `bootstrap_failed` is true.

## Validation Rules

- A bootstrap failure in `check`, `parse`, or `fetch` must produce final status `1`.
- A successful run must retain final status `0`.
- Usage errors remain status `2` and are outside this state transition.
