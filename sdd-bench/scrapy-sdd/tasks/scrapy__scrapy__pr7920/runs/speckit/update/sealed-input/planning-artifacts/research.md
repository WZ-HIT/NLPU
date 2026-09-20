# Research: Bootstrap Error Exit Codes

## Decision: Use the existing `CrawlerProcess.bootstrap_failed` signal

**Rationale**: `crawl` and `runspider` already translate this signal into `self.exitcode = 1`.
Reusing it keeps behavior consistent and avoids a new failure-detection mechanism.

**Alternatives considered**:

- Infer failure from output text: rejected because it is brittle and locale/format dependent.
- Set status in `cmdline.execute`: rejected because bootstrap state belongs to the command's
  crawler process and existing command implementations already own this translation.

## Decision: Apply the change to exactly `check`, `parse`, and `fetch`

**Rationale**: These are the commands named by the requested behavior; `crawl` and
`runspider` already implement it.

**Alternatives considered**:

- Change all crawler-based commands: broader than requested and risks unrelated behavior.

## Decision: Verify through command-level tests

**Rationale**: Process exit status is an external contract, so integration-style tests using
the existing command runner are the most reliable evidence.

**Alternatives considered**:

- Unit-test only the assignment: insufficient to prove the command-line process returns `1`.
