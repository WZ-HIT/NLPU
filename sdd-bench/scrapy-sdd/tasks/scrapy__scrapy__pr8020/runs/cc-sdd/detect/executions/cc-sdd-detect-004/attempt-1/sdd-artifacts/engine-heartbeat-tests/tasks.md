# Implementation Plan

- [x] 1. Read the PR task input and scope the detect stage
  - Read /task-input/task.md (repo scrapy/scrapy, PR 8020, base ed98aafd).
  - Scope: planning artifacts only; no tests executed, no project code or test files
    modified.
  - _Boundary:_ artifacts under .kiro/specs/ only.

- [x] 2. Locate the engine heartbeat mechanism
  - scrapy/core/engine.py: _Slot.heartbeat (create_looping_call),
    ExecutionEngine._SLOT_HEARTBEAT_INTERVAL = 5.0, _start_request_processing(),
    _Slot._maybe_fire_closing().
  - _Depends:_ 1

- [x] 3. Locate candidate test files
  - tests/test_engine_loop.py (the tests that wait on the heartbeat).
  - tests/test_engine_close_spider.py, tests/test_engine.py,
    tests/test_extension_memusage.py, tests/test_utils_asyncio.py.
  - Verified that each candidate path exists as a repository-relative test path.
  - _Depends:_ 2

- [x] 4. Write the detection draft
  - Exactly one .kiro/specs/detection-draft.json containing only candidates, each with
    path, symbols and reason.
  - _Depends:_ 3

- [x] 5. Write the remaining planning artifacts in the mounted planning directory
  - requirements.md, design.md, tasks.md, spec.json under
    .kiro/specs/engine-heartbeat-tests/.
  - _Depends:_ 4
