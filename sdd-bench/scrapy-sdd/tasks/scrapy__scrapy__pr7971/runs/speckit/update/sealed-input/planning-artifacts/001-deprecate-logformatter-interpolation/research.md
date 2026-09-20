# Phase 0 Research: Log Formatter Dict Interpolation Deprecation

## Decision: Warn and interpolate when `args` is absent

**Rationale**: The current adapter returns only `(level, message)` when `args`
is missing, so a legacy message containing mapping placeholders reaches the
logging call unformatted. Restoring interpolation with the returned dictionary
recovers the pre-#7936 output while a deprecation warning gives users a migration
path. Supplying the returned dictionary as the mapping argument to the logging
call keeps interpolation lazy, matching the existing explicit-mapping path.

**Alternatives considered**:

- Raise an error for missing `args`: rejected because the pull request exists to
  alleviate an incompatibility, not to enforce a breaking change.
- Silently interpolate with the returned dictionary: rejected because users
  would never learn to migrate before the legacy path is removed.
- Warn only and leave the message unformatted: rejected because it changes
  observable log output and breaks the compatibility being restored.

## Decision: Reuse the project deprecation warning convention

**Rationale**: Scrapy centralizes deprecation warnings through its deprecation
utilities and warning class, and tests already assert those warnings. Reusing
them keeps the new warning consistent and suppressible like other Scrapy
deprecations.

**Alternatives considered**:

- A plain `UserWarning`: rejected because it would not participate in Scrapy's
  documented deprecation policy.

## Decision: Do not change `LogFormatter` method return values

**Rationale**: The incompatibility is in how results are adapted for logging,
not in what the formatter returns. Leaving `scrapy/logformatter.py` untouched
keeps the default formatter and every subclass contract stable.

**Alternatives considered**:

- Adding an explicit legacy marker to the result TypedDict: rejected as an
  unnecessary public-API expansion.

## Decision: Keep explicit tuple and mapping `args` behavior unchanged

**Rationale**: These are the documented, supported paths. Any warning or
additional formatting there would create a new incompatibility while fixing an
old one.

**Alternatives considered**:

- Deprecating tuple `args` as well: rejected as out of scope and unsupported by
  the pull request intent.
