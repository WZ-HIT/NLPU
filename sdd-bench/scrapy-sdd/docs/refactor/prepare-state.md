# 可恢复 prepare 状态

运行：`PYTHONPATH=sdd-bench/scrapy-sdd python3 -m batch.prepare_run <experiment-config.json> --output-dir <new-directory>`。本阶段不发起模型请求。状态保存在 `state.json`，最终不可覆盖的产物是 `prepared-manifest.json`。`state.json` 仅含 `prepared_id`、各步骤证据摘要和文件数；不保存凭据值或 gold 值。

步骤按 `inputs`、`baseline`、`images`、`scaffold`、`gold`、`preflight`、`update_policy` 排列。每次恢复都会重新验证文件与身份，并将证据 SHA-256 与已记录的步骤摘要比较；不凭 `VERIFIED` 字样跳过检查。哈希或身份变化立即停止。只有全部步骤通过才写入冻结清单。若冻结清单已存在，重新验证它与全部引用并确认与当前配置编译结果一致，然后直接复用。输出目录必须位于仓库内。

在编译之前，缺失的 provision report、镜像配方和部署、脚手架 task、Update policy 会调用原 `provision_plan`、镜像构建脚本、`scaffold_tasks` 和 `select_update_policy`。每次生成后立即对照兼容配置中的固定哈希；不能重现时停止，绝不改写固定身份。镜像构建输出不进入状态或日志。

`inputs` 使用现有计划输入校验和 P1 的固定哈希；`baseline` 验证基线锁；`images` 使用现有镜像配方校验并核对部署锁、image ID 与镜像审计；`scaffold` 验证 task manifest、Compose 和公开 task 输入；`gold` 验证隔离审计与 Agent 可见文件列表，若整体审计完全不存在则调用原 `run_audit`；`preflight` 验证运行边界和 Compose 锁，若摘要完全不存在则调用原 `run_preflight`；`update_policy` 用原策略校验逻辑核对所有固定策略。底层实现若发现部分残留或封存冲突会拒绝覆盖，prepare 不清理这些产物。

P1 兼容配置已经固定 `task_manifest`、镜像锁和 Update policy 的文件哈希。因此 prepare 只接受生成结果恰好匹配已固定哈希的情况；带时间字段的新产物通常不能重现历史摘要。新实验宜先用原底层流程创建并固定这些身份，再运行 prepare。

P3 读取方式：`from batch.prepare_run import load_prepared; manifest = load_prepared(path)`。函数重算 `prepared_id`，按 schema 检查目标和镜像表，并逐项复核固定文件及准备证据。运行前仍须将实际容器 image ID 与清单 `images` 对比。示例 `simulation-3pr/prepared-manifest.json` 从历史 3 PR 产物模拟首次准备生成，未调用模型。
