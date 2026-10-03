# 独立 Detect 轮次（配置 v2）

用户维护一份配置，例如 [`scrapy-30pr-detect-rerun-v1.json`](../../batch/experiments/scrapy-30pr-detect-rerun-v1.json)。`prs` 是本轮要跑的 PR 名单；删去某些编号即可缩小本轮范围。每个 PR 必须恰好出现在一个固定来源批次中。三个来源文件分别提供 3、7、20 个 PR，示例配置选择全部 30 个，按 3 种方法展开为 90 个 Detect 目标。来源路径和 SHA-256 固定，变更后 prepare 会阻止执行。配置 v2 只接受 `stages: ["detect"]`，不生成 Update 目标或策略。

配置中的 `experiment_id` 是易读的实验名称，`--round` 是本次运行的标签；页面使用 `round-<24 hex>` 作为批次唯一 ID，它由配置快照和标签确定性生成。同一实验换标签可重跑，旧结果仍有独立身份。

一个轮次名标识一次从 baseline 新建的实验。prepare 会先把配置字节保存到 `batch/round-configs/<sha256>.json`，旧轮次继续引用这份快照；日后修改工作配置或 PR 列表不会使旧结果失效。相同配置内容和相同轮次名得到相同 `round-<24 hex>`；换轮次名得到独立目录，不需要 `git restore` 整个仓库。`run_id` 沿用来源批次的阶段身份，但工作区、ledger 和所有运行产物都保存在 `batch/runs/<round-id>/` 下。历史 `tasks/`、`batch/pilot/` 和旧 ledger 保持只读。

在 `sdd-bench/scrapy-sdd` 目录运行：

```bash
CONFIG=batch/experiments/scrapy-30pr-detect-rerun-v1.json
ROUND=rerun-001
python3 bin/sdd-experiment prepare "$CONFIG" --round "$ROUND"
python3 bin/sdd-experiment run "$CONFIG" --round "$ROUND" --stage inspect
python3 bin/sdd-experiment run "$CONFIG" --round "$ROUND" --stage detect --execute
python3 bin/sdd-experiment results summary --config "$CONFIG" --round "$ROUND"
python3 bin/sdd-experiment evaluate "$CONFIG" --round "$ROUND" --kind compliance
python3 bin/sdd-experiment evaluate "$CONFIG" --round "$ROUND" --kind detect
python3 bin/sdd-experiment archive "$CONFIG" --round "$ROUND"
python3 bin/sdd-experiment results report --config "$CONFIG" --round "$ROUND"
```

`prepare` 校验固定来源、计划、基线和镜像，创建每轮独立工作区，运行 gold 隔离审计和 Docker preflight，然后冻结 `prepared-round.json`。prepare 和 inspect 都不请求模型；**只有** `run --stage detect --execute` 发起正式 Agent 调用。prepare 中途失败时，使用相同命令续跑；已有任务必须核验后才能复用，哈希冲突会停止。`run --resume` 跳过已封存目标；失败目标按原运行器的 `--retry <target-key>` 或 `--recover-detect <target-key>` 处理。整轮中断后，`run --stage detect --execute --resume --retry-failed` 会为失败或中断的 Detect 目标开新 attempt，跳过已封存目标，并运行尚未开始的目标；旧 attempt 的 ledger 和文件保留。不要把新轮次当作旧轮次的重试：新轮次使用新的 `ROUND`。

目标键是 `task_id:method:stage:run_id:mode`，Detect 的 mode 为 `none`。轮次 manifest v2 将此键对应的任务、输入文件 SHA-256、镜像锁、静态审计、preflight 和目标 ID 冻结。运行器仍使用追加式 ledger；结果视图 v2、页面、合规报告和宿主机 Detect 指标用同一键。全部 90 个 Detect 目标必须封存后，才可生成完整合规报告和归档。`evaluate --kind detect` 在宿主机读取隐藏 gold 并写入 `Log/reports/detect-metrics/`；gold 原始文件不进入 Agent 工作区或归档。指标沿用既有 Detect hit-rate v2 口径。未全数封存时，`evaluate --kind detect` 会被 Detect 屏障拒绝；如需查看明确标记为 `PARTIAL` 的暂时指标，可在宿主机运行 `python3 bin/sdd-detect-metrics check --batch <round-id>`。它只写 `Log/reports/detect-metrics/<round-id>.json`，页面读取此报告；失败目标不会被悄悄剔除。补跑后需重新执行 `check` 更新报告。

`archive` 将轮次的配置、固定输入引用、静态校验证据、ledger、封存产物、结果视图、报告和已有指标复制到 `Log/reports/round-archives/<round-id>/files/`，并写入各文件 SHA-256 清单。此目录与运行工作区分离，可用 `batch.round_archive.verify_archive(path)` 复核。归档不包含 baseline 工作区或原始 gold，归档目录仅宿主机可读。尚未完成的轮次保留在各自 `batch/runs/<round-id>/`，可继续运行，但不能标记为完整归档。完整归档后本轮禁止再写 ledger；若要重跑，请换一个 `ROUND`。

旧配置 v1 与不带 `--round` 的命令继续按原参数语义运行，历史结果仍可用 `results list/report` 查看。修改工作配置后，可用 `results report --experiment <旧 round-id>` 查看旧轮次；如需续跑旧轮次，应将 `--config` 指向其 `batch/round-configs/<sha256>.json` 快照。不要用 `batch/experiments/scrapy-3pr-both-pilot-v1.json` 配置这次 30 PR Detect 重跑：它描述的是旧 3 PR Detect+Update 实验。
