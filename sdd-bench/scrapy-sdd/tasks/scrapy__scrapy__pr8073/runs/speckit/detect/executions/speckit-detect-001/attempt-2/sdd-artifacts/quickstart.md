# Detection Quickstart

## Prerequisites

- Read-only checkout at commit `11079cb1c85b9e75a39a7269943c69d1a975d485`.
- Writable planning mount at `/workspace/specs`.
- No test execution is permitted.

## Inspect Candidates

```bash
grep -RIn --exclude-dir=.git --exclude-dir=specs \
  'DirtyReactorAggregateError' /workspace/tests
```

Expected evidence:

- One match in `tests/test_downloader_handler_twisted_ftp.py`.
- Two matches in `tests/utils/bases/download_handlers_http.py`.

## Validate the Draft

```bash
python3 - <<'PY'
import json
from pathlib import Path

draft = json.loads(Path("/workspace/specs/detection-draft.json").read_text())
assert list(draft) == ["candidates"]
assert draft["candidates"]
for candidate in draft["candidates"]:
    assert list(candidate) == ["path", "symbols", "reason"]
    assert candidate["path"].startswith("tests/")
    assert candidate["symbols"]
PY
```

This validation reads the draft only; it does not import or run project tests.

## Expected Outcome

Two candidate files with three affected test symbols total, ready for the update
stage to decide whether each historical skip can be removed.
