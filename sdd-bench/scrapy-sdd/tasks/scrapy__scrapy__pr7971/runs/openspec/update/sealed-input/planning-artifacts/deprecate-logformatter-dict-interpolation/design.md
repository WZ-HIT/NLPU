## Context

`logformatter_adapter()` currently forwards tuple arguments to the logging
module for lazy formatting and forwards a dictionary as one positional
argument. Before lazy formatting was introduced, the adapter interpolated the
message eagerly with `msg % args`. The compatibility-sensitive case is a custom
formatter whose dictionary `args` and percent-mapping message depended on that
eager behavior.

## Goals / Non-Goals

The change preserves existing dictionary-based behavior for one deprecation
cycle, warns callers, and keeps tuple interpolation lazy. It does not change
the built-in formatter result schema or remove dictionary support.

## Decisions

- Detect a non-empty dictionary before forwarding arguments to logging.
- Emit `ScrapyDeprecationWarning` with a migration message.
- Interpolate the message eagerly with the dictionary, matching the pre-lazy
  behavior and avoiding a behavior break.
- Leave tuple arguments unchanged so logging remains responsible for
  interpolation.
- Document tuple arguments as the supported forward-compatible form.

## Risks / Trade-offs

[Warning noise for custom formatters] -> The warning is emitted only when a
non-empty dictionary is returned, and the migration is documented.

[Different interpolation timing for dictionaries] -> Eager interpolation is
intentional for compatibility until dictionary support is removed.

## Migration Plan

Formatter authors should return tuple arguments such as `(value,)` and use
tuple-style placeholders such as `%s`. Dictionary arguments continue to work
and emit a deprecation warning.
