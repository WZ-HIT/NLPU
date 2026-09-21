# Prepared manifest 运行接口

入口仍为 `sdd-pilot`（或调用 `batch.pilot_cli.main`），新增 `--manifest <prepared-manifest.json>`，与旧的 `--config` 互斥。prepared manifest 支持 `detect`、`update`、`all`、`inspect`、`probe`、续跑 `--resume` 和逐目标 `--retry <ledger-key>`。旧配置接口继续可用。

- `inspect`：校验 manifest、全部固定引用、ledger 哈希链并返回正式目标状态；不创建 run 目录，不追加 ledger，不写报告。`status` 是旧接口的只读别名。
- `probe`：调用原阶段执行器的 `dry_run=True` 路径，不调用 Agent；追加 action 为 `probe`、state 为 `DRY_RUN_READY` 或 `BLOCKED` 的 ledger 事件，并写 `probe-report*.json`。probe 是观察事件，不覆盖正式状态，也不影响续跑或重试判断。
- `detect`、`update`、`all`：继续使用原 `detect_targets`、`update_tests`、追加式 ledger 和阶段状态。prepared run 使用 `prepared_id` 作为新 ledger 的 `batch_id` 和 `batch/runs/<prepared_id>/` 目录，不触碰历史批次 ledger。

全批 Detect 屏障保持不变：正式 Update 开始前，manifest 中所有 Detect 目标必须为 `DETECT_SEALED`，屏障继续校验同 task/method 的正式 seal。`sealed-detect` 和 `self-directed` 分别传入 manifest 固定的策略文件；原执行器负责隔离 Detect 输入。原 `enforce_update_scope` 继续把生产文件修改视为违规；sealed 模式还要求修改属于 Detect 候选测试集合。

## 状态映射

| 旧接口/状态 | prepared 接口/状态 |
| --- | --- |
| `batch_id` 运行目录 | `prepared_id` 运行目录 |
| `status` | `inspect`（`status` 保留为别名） |
| `--dry-run` / action `dry-run` | `probe` / action `probe`；旧参数仍兼容 |
| `PLANNED`、`PREFLIGHT_READY`、`DETECT_RUNNING`、`DETECT_SEALED` | 不变 |
| `UPDATE_POLICY_SELECTED`、`UPDATE_READY`、`UPDATE_RUNNING`、`UPDATE_SEALED` | 不变 |
| `FAILED`、`BLOCKED`、`SKIPPED_RESUME` | 不变 |

P1 的目标身份仍是 `(task_id, method, stage, mode, run_id)`，`target_id` 原样进入输出。为兼容旧 ledger，命令行 `--retry` 使用的 ledger key 字符串仍为 `task_id:method:stage:run_id:mode-or-none`。

## P4 读取字段

运行摘要包含 `prepared_id`、`batch_id`（等于 prepared ID）、`command`、`selected_count`、`status` 和 `results`。每个正式结果包含 `target_id`、兼容 ledger key `target`、`state`、`update_mode`、`attempt`、`ledger_sequence` 和原阶段执行器的 `result`；Detect 完成摘要还含 `detect_barrier_sha256`。`result` 保留 checkpoint、seal、候选 patch、范围审计等原字段。P4 应以 `target_id` 关联 P1 目标，以 `ledger_sequence` 定位不可变事件，并复核阶段结果中引用的文件哈希。
