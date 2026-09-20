# Tasks: CI warnings to errors (planning)

Planning-stage tasks only; no implementation is performed in this run.

- [ ] T1 — Escalate warnings to errors in `[tool.pytest.ini_options].filterwarnings` while preserving the existing three scoped ignores.
- [ ] T2 — Review each warning-emission site under `scrapy/` and decide fix-in-code vs scoped-ignore vs test-expectation.
- [ ] T3 — Update tests that rely on warnings being non-fatal so that intentional warnings are asserted explicitly.
- [ ] T4 — Re-check shared test bases (`tests/utils/bases/`) for inherited warning behaviour.
- [ ] T5 — Confirm CI runs a single global policy (no per-environment warning toggles).

## Detection handoff

Candidate test files for the change are recorded in `../detection-draft.json` (44 candidates, statically derived). Each candidate names the relevant symbols and why the warnings-as-errors policy reaches that file.
