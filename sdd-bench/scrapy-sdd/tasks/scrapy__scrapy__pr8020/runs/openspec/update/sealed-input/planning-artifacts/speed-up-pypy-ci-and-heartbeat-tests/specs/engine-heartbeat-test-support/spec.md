## Purpose

Defines how tests that depend on the engine slot heartbeat make progress, so
that they stay deterministic and fast instead of waiting for the production
heartbeat interval.

## ADDED Requirements

### Requirement: Heartbeat-dependent tests do not wait for the production interval

Tests that need the engine slot heartbeat to resume processing scheduled
requests SHALL complete without waiting multiple production heartbeat
intervals.

#### Scenario: Requests appear while start-request iteration is paused

- **WHEN** a test pauses the scheduler, enqueues requests, and then unpauses
  it while the engine is otherwise idle
- **THEN** the test observes those requests being processed without waiting a
  full production heartbeat interval

### Requirement: Test heartbeat preserves the production contract

Any heartbeat used by the tests SHALL keep the production behavior: while the
slot is open it keeps re-scheduling the engine's next call, and it stops when
the slot closes.

#### Scenario: Slot closes while the test heartbeat is running

- **WHEN** the spider slot closes while the test heartbeat is running
- **THEN** the heartbeat stops and no further scheduled calls are made

#### Scenario: Test heartbeat is not shared with production

- **WHEN** tests use a shortened or stubbed heartbeat
- **THEN** crawls started outside the test suite still use the production
  heartbeat interval
