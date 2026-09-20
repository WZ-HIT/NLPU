# Design Document

## Overview

Detection-only design: it defines how the candidate test files for scrapy/scrapy#8020 are
derived and what the single detection artifact contains. The PR itself (shorter heartbeat
waiting in tests, less subprocess coverage work in the PyPy CI job) is not implemented
here.

## Mechanism under test

`ExecutionEngine._start_request_processing()` starts `self._slot.heartbeat` with
`_SLOT_HEARTBEAT_INTERVAL = 5.0`. The heartbeat repeatedly calls `nextcall.schedule()`,
which is what keeps a crawl moving when the scheduler reports
`has_pending_requests() == True` while `next_request()` returns `None` (paused scheduler):
nothing else reschedules `nextcall` in that state. `_Slot._maybe_fire_closing()` cancels
`nextcall` and stops the heartbeat when the slot closes. The heartbeat object comes from
`create_looping_call`, i.e. `AsyncioLoopingCall` or Twisted's `LoopingCall`.

## Detection strategy

1. Locate the heartbeat definition, interval constant and lifecycle calls in
   `scrapy/core/engine.py`.
2. Find test modules that (a) block on the heartbeat interval, (b) assert heartbeat
   lifecycle through the slot, (c) stub `create_looping_call` for the engine, or (d)
   unit-test the looping-call primitive.
3. Record pytest node identifiers per candidate plus the evidence.

Evidence gathered at the base commit:

| Candidate | Evidence |
|---|---|
| `tests/test_engine_loop.py` | `MemoryScheduler.pause()/unpause()` with `seconds = 2` sleeps in `TestMain::test_sleep`; timing-sensitive `TestRequestSendOrder.seconds = 0.1  # increase if flaky` |
| `tests/test_engine_close_spider.py` | `del engine._slot.heartbeat` in `test_exception_slot`; slot close paths |
| `tests/test_engine.py` | `ExecutionEngine` end-to-end crawls; idle / close-reason handling |
| `tests/test_extension_memusage.py` | monkeypatches `engine_mod.create_looping_call` with `OneShotLoop` to avoid a background heartbeat and engine start/stop races |
| `tests/test_utils_asyncio.py` | `TestAsyncioLoopingCall` unit tests for the looping-call primitive used as the heartbeat |

## File Structure Plan

- `.kiro/specs/detection-draft.json` - the single detection draft (candidates array only).
- `.kiro/specs/engine-heartbeat-tests/requirements.md` - requirements.
- `.kiro/specs/engine-heartbeat-tests/design.md` - this document.
- `.kiro/specs/engine-heartbeat-tests/tasks.md` - task list and status.
- `.kiro/specs/engine-heartbeat-tests/spec.json` - spec metadata.

No files outside the mounted planning directory are written; no repository test or
production file is touched.

## Risks

- The 5 s interval cannot be observed without running tests, which this stage forbids;
  candidates are therefore derived from static evidence.
- The timing-only `TestRequestSendOrder` tests may be incidental rather than the PR target;
  they stay in the draft with an explicit reason so the reviewer can drop them.
