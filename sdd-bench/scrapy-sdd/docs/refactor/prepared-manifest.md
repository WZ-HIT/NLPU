# Prepared manifest v1 契约

编译入口：`PYTHONPATH=sdd-bench/scrapy-sdd python3 -m batch.prepare <config.json> --output <new-manifest.json>`。编译只读取已存在的输入，不运行模型、Docker 或历史执行器，也不改写历史证据。输出路径必须是新文件。

用户配置采用 `schemas/experiment-config-v1.schema.json`：`experiment_id`、带 SHA-256 的 `source_batch`、PR 数字数组、方法数组、阶段数组、Update 模式数组，以及 `evaluation`（`none` 或带哈希的 `host-plan`）。`source_batch` 是已有 `batch-run-v1` 配置的兼容绑定：从其中取得已批准的 plan、task manifest、Update policy 和原有 `run_id`。因此历史 run ID 原样保留；新 `target_id` 和 `prepared_id` 由规范 JSON 的 SHA-256 截取生成，没有时间戳。只允许配置中明确选择的 PR、方法、阶段和模式；Update 必须同时包含 Detect。

输出版本是 `schema_version: 1`、`manifest_type: PREPARED_EXPERIMENT`，由 `schemas/prepared-manifest-v1.schema.json` 定义。顶层字段为：

- `experiment_id`：用户指定的稳定名称。
- `prepared_id`：`prepared-` 加上不含该字段的整个 manifest 规范 JSON SHA-256 前 24 位十六进制字符。输入身份或目标变更会改变它。
- `inputs.user_config`、`inputs.source_batch`：仓库相对路径和原始文件 SHA-256；`inputs.batch_id`、`inputs.approved_plan`：历史批次和批准输入身份；`inputs.evaluation`：评估方案及其可选的文件身份。
- `images`：按 `base_sha` 排序的镜像身份表，每个实际使用的 base 恰有一项。每项含 `baseline_lock` 和 `deployment_lock` 的仓库相对路径及文件 SHA-256，以及 `agent`、`baseline` 镜像的 tag 和 `sha256:` image ID。编译时要求部署锁状态为 `READY`、base SHA 相符，且其 `baseline_lock_sha256` 与基线锁文件一致。清单不通过 tag 单独推断镜像内容。
- `target_count`、`targets`：编译所得目标数与有序列表。每项含 `target_id`、`task_id`、`method`、`stage`、`mode`、`run_id`、`base_sha`、`task_manifest`、`policy`。Detect 的 `mode` 和 `policy` 为 `null`；Update 的 `policy` 是带哈希的文件身份。

`target_id` 是 `target-` 加上 `(task_id, method, stage, mode, run_id)` 规范 JSON SHA-256 前 24 位。目标顺序由用户配置的 PR、方法、模式顺序决定；每个 task/method 先列 Detect 再列 Update。P2、P3 在使用前应校验 schema、重算 `prepared_id`、复核所有输入哈希及 `images` 中的锁文件哈希，检查每个目标的 `base_sha` 在镜像表中恰有一个对应项，并在运行前将实际镜像 ID 与清单比对；不能把清单里的 `target_count` 或 ID 单独当作输入仍有效的证明。清单只是准备结果，不代表目标已经运行或封存。

历史对照示例在 `batch/experiments/`。3 PR 完整实验编译为 27 个目标；20 PR Detect 编译为 60 个目标。P0 记录的 20 PR 五个未封存目标仍在目标集合中，prepared manifest 不推测其结果。
