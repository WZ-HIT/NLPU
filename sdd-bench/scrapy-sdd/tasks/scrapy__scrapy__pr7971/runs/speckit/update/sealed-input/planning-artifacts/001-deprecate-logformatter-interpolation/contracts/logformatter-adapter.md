# Contract: `logformatter_adapter`

## Input

A log formatter result dictionary shaped as:

```text
{"level": <int?>, "msg": <str|null?>, "args": <mapping|tuple|null?>}
```

## Output

Positional arguments for a stdlib `logging` call:

```text
(level, message)                      # no interpolation
(level, message, *tuple_args)         # explicit tuple interpolation
(level, message, mapping_args)        # explicit mapping interpolation
(level, message, result_dict)         # deprecated legacy dict interpolation
```

## Guarantees

- Explicit mapping and tuple `args` are interpolated exactly once by logging.
- Missing or empty `args` with a placeholder-free message is logged unchanged.
- Missing or empty `args` that relies on dictionary interpolation is logged with
  the same rendering as before the incompatibility and emits a deprecation
  warning.
- The `LogFormatter` method return shape, including `None` for suppressed
  messages, is unchanged.
