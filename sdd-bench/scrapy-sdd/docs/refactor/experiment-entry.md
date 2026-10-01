# Unified experiment entry and acceptance

`bin/sdd-experiment` uses one `batch/experiments/*.json` config throughout.
The P1 compiler checks its pinned source and derives the same prepared ID on
every call. `prepare` writes the frozen manifest to
`batch/prepared/<experiment-id>/prepared-manifest.json` by default; use
`--output-dir` for preparation and the matching `--prepared-dir` for later
commands when a different in-repository directory is needed. Later commands
recompile the user config, verify the frozen manifest and every P2 reference,
and refuse a mismatch.

| Command | Action |
| --- | --- |
| `prepare CONFIG` | Resume P2 checks and freeze the prepared manifest; it may build a missing pinned image, but makes no model request. |
| `run CONFIG` | Read-only `inspect` of the formal ledger; no file is written. |
| `run CONFIG --stage probe` | Record a dry-run probe in the ledger; no Agent call. |
| `run CONFIG --stage detect\|update\|all --execute` | Run P3 formal stages with the global Detect barrier, mode-specific visibility and append-only ledger. `--resume`, `--retry`, `--recover-detect`, `--task`, `--method`, `--mode` and `--no-archive` pass through to P3. |
| `evaluate CONFIG --kind compliance` | Verify and publish the operational report for a fully sealed batch. |
| `evaluate CONFIG --kind quality` | Use the pinned host plan to score test-update quality after seal verification; hidden gold stays on the host. |
| `evaluate CONFIG --kind both` | Run compliance, then host quality evaluation. |
| `results summary --config CONFIG` | Rebuild the gold-free P4 view for the prepared run and print indexed targets and states. |
| `results list\|report\|serve` | Read historical and prepared result pages through the existing viewer. `report --config CONFIG` selects the prepared page; `report --experiment ID` selects a historical page. `--output PATH` chooses an HTML file. |

Every ledger-mutating `run` action writes a derived
`batch/runs/<prepared-id>/result-view.json` after P3 returns, so the existing
page discovers prepared batches. `inspect` writes neither ledger nor view.
No command launches a formal Agent unless `run --stage detect`, `update` or
`all` is paired with `--execute`. `evaluate` can execute host tests, so it is
an explicit separate command. A Detect-only config with `evaluation.kind=none`
cannot request quality scoring. A partial batch can be viewed through `results`;
final compliance and quality evaluation still require the applicable sealed
evidence.

## Compatibility

`bin/sdd-batch`, `bin/sdd-pilot`, `bin/sdd-image`, the stage launchers,
`tools/sdd-results.py` and `run-pilot.sh` remain callable with their existing
arguments. `sdd-pilot --config` continues to read historical batch configs;
`--manifest` reads prepared runs. `run-pilot.sh` still selects its old default
config through `SDD_BATCH_CONFIG`. The new CLI calls P2, P3 and P4 functions
directly, so the old wrappers are kept only where they have an actual
executable caller. No duplicate uncalled wrapper was removed: repository
search found the existing wrappers referenced by `bin/*` or `run-pilot.sh`.

## Acceptance record

Prerequisite commits: P0 `d120178`, P1 `0d6f13f` and image identity fix
`8b963b0`, P2 `4628a63`, P3 `b5393a5`, P4 `b8734d8`, `522516a` and
`a051c00`. The historical image recipe verifier was repaired in `600daac`:
five frozen early recipes are checked against their pinned masked template
hash; sixteen later recipes remain compared byte for byte after rule masking.
No historical recipe or evidence file was changed.

The two P1 example configs expand to 27 and 60 unique P3 keys, respectively.
Each set equals P0 and the corresponding P4 result view. The frozen three-PR
simulation manifest maps 27 targets uniquely to P3. The saved
`metric-comparison.json` records equal comparable counts and row scores for
Detect metrics v1/v2; it is a recorded comparison, not a new host scoring run.

A fake-Agent acceptance test exercises the new `prepare → Detect → Update →
evaluate` dispatch, including the real P3 ledger and Detect barrier. P2
recovery, gold isolation, mode visibility, Update scope, retries and read-only
inspect are covered by the existing batch tests. The SDD test suites pass
without Docker or model calls. Historical `sdd-pilot status` and the new
`results list` remain read-only. No paid experiment was started.
