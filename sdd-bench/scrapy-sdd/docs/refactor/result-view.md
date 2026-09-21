# Target result view v1

`batch/result_view.py` builds a deterministic, gold-free view from either a
`batch-run-v1` config or a `PREPARED_EXPERIMENT` manifest plus its append-only
ledger. The JSON contract is `schemas/target-result-view-v1.schema.json`.

`targets` is an object indexed by the P3 ledger key
`task_id:method:stage:run_id:mode-or-none`. Every row also carries P2's
`target_id`, the latest formal ledger event commitment, the resolved state and
attempt, and (when present) the immutable seal path and SHA-256. `target_order`
preserves the source-manifest order. The view only references seals; it never
rewrites them and contains no gold or evaluation values.

The operational report, Detect metrics, host evaluator, and `sdd-results` page
reader use this index. `sdd-pilot report` and `evaluate-host` accept either
`--config` or `--manifest`; prepared evaluation additionally verifies that the
manifest pins the selected host plan and its legacy source batch before gold is
constructed. A recorded `batch/runs/<batch-id>/result-view.json` is
preferred by the page reader; legacy configs remain readable while historical
views are migrated. Prepared-only runs are discoverable through the view's
pinned source reference.

Host evaluation plan v2 replaces the historical `sealed_target_count: 27`
constant with an integer count checked against the result view; v1 remains
readable for the historical three-PR plan.

Detect metrics are `detect-metrics-v2`: scoring formulas are unchanged, while
each row now binds `target_key`, `target_id`, the ledger event, the seal, and the
result-view hash. The version upgrade prevents a v1 reader from silently
interpreting the stronger evidence-binding contract as the old document.

Historical validation:

- `scrapy-3pr-both-pilot-v1`: 27 targets, 27 terminal; 9 Detect and 18 Update.
- `scrapy-20pr-detect-v1`: 60 Detect targets; 55 terminal and 5 failed.
- `scrapy-3pr-detect-v2`: 9 Detect targets, all terminal, used for the v1/v2
  metric comparison in `metric-comparison.json`.

These counts and states match `baseline.json`; rebuilding the views does not
change any referenced seal hash.
