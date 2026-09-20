# Requirements Document

## Introduction

PR scrapy/scrapy#8020 ("Speed up the PyPy CI job and the tests that wait on the engine
heartbeat") targets base commit ed98aafd0f6301647916c86811acacd0a1b59dbd. It removes the
dominant PyPy job slowdown caused by coverage measurement of subprocesses, and removes the
waiting that some tests spend on the engine heartbeat. This spec covers only the detection
of the tests that observe or wait on that heartbeat.

## Boundary Context (Optional)

- In scope: identifying test files that wait on or assert ExecutionEngine's per-slot
  heartbeat (scrapy/core/engine.py: _Slot.heartbeat, started from
  _start_request_processing with _SLOT_HEARTBEAT_INTERVAL = 5.0, stopped from
  _Slot._maybe_fire_closing), plus the PyPy coverage scope of the CI job.
- Out of scope: implementing the PR, changing scrapy/ production code, or changing any
  test file in this task. Only the detection draft is produced.
- Adjacent expectations: the heartbeat is created through
  scrapy.utils.asyncio.create_looping_call, so the looping-call contract and the
  tests/utils stubbing helpers are adjacent surfaces.

## Requirements

### Requirement 1: Identify tests blocked on the engine heartbeat
**Objective:** As a reviewer, I want the tests that wait on the engine heartbeat to be
listed, so that the change is verified against the exact tests it speeds up.

#### Acceptance Criteria
1. When the heartbeat reschedules nextcall on a fixed interval, the detection result shall
   name every test module whose crawl only advances because of that interval.
2. The detection result shall name the pytest symbols (Class::test) inside each candidate
   module that depend on the heartbeat.
3. Where a test stubs the heartbeat through create_looping_call instead of waiting on it,
   the detection result shall list that module as a candidate as well.

### Requirement 2: Identify engine close/stop paths that touch the heartbeat
**Objective:** As a reviewer, I want the tests that assert heartbeat start/stop behavior,
so that lifecycle regressions stay covered.

#### Acceptance Criteria
1. The detection result shall include the module that deletes engine._slot.heartbeat to
   exercise slot-close failure handling.
2. The detection result shall include the module that crawls through ExecutionEngine end
   to end, where the heartbeat is started and stopped.

### Requirement 3: Keep detection output machine-readable and scoped
**Objective:** As the downstream verification stage, I want one machine-readable draft, so
that candidate tests can be selected without parsing prose.

#### Acceptance Criteria
1. The planning directory shall contain exactly one detection-draft.json.
2. detection-draft.json shall contain only a candidates array, each entry exposing path,
   symbols, and reason.
3. Every path shall be a repository-relative test path, and every recorded file shall
   exist.
4. No project code or test file shall be modified, and no test shall be executed.
