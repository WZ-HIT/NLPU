# SDD 重构历史对照基线

## 范围与输入身份

基线固定在提交 `326c7ac9daf24ee2a462a3398825be2bb7134679` 的历史证据。机器可读清单见同目录 `baseline.json`；其中逐项列出目标的 `task_id`、`method`、`stage`、`mode`、`run_id`、task manifest 与 policy 的路径及 SHA-256、`base_sha`、ledger 终态与封存事件序号、seal 路径及 SHA-256。`mode: null` 表示 Detect。清单只引用历史文件和摘要，不包含隐藏 gold 内容。

| 实验 | 目标 | 配置与输入 | 历史记录 | 封存状态 |
| --- | --- | --- | --- | --- |
| 3 PR 完整实验 `scrapy-3pr-both-pilot-v1` | PR 8064、8067、8073；每 PR × `openspec`、`speckit`、`cc-sdd` × 1 Detect + 2 Update（`sealed-detect`、`self-directed`），共 27 | `batch/pilot/scrapy-3pr-both-pilot-v1.json`；批准计划 `scrapy-3pr-pilot-8073-8064-8067-v1`；各 task manifest 和 Update policy 的身份见 JSON | 204 条 ledger；Detect barrier、final report、audit、evidence manifest；Prompt 10 主机评估计划与产物 | 27/27 封存：9 Detect、18 Update |
| 20 PR Detect `scrapy-20pr-detect-v1` | 配置中 20 个 PR × 3 种方法 × 1 Detect，共 60；没有 Update | `batch/pilot/scrapy-20pr-detect-v1.json`；批准计划为 `scrapy-20pr-detect-v2`；各 task manifest 的身份见 JSON | 404 条 ledger 和 dry-run report；没有全局 Detect barrier、final report 或评估产物 | 55/60 封存；5 个未封存 |

批准计划、provision report、配置、ledger 与已有终结产物的路径和 SHA-256 均在 JSON 中。配置里的 `approved_plan.sha256`、`provision_report_sha256`、`task_manifest.sha256`、`policy.sha256` 是原始输入身份；清单另记录实际文件摘要供复核。

## 历史缺口

20 PR Detect 下列目标在 ledger 中最后为 `FAILED`，没有对应 seal；因此该批次不能视为完整封存，也没有可引用的完整评估指标。未补造结果。

| PR | 方法 | run_id |
| --- | --- | --- |
| 7702 | speckit | `speckit-detect-004` |
| 7808 | speckit | `speckit-detect-004` |
| 7985 | speckit | `speckit-detect-004` |
| 7985 | cc-sdd | `cc-sdd-detect-004` |
| 8020 | speckit | `speckit-detect-004` |

20 PR ledger 中部分已封存目标的末条事件为 `SKIPPED_RESUME`。封存判定同时要求该目标曾有 `DETECT_SEALED` 事件及匹配的 seal 文件，而不是单看末条事件。3 PR 的 final report 为 `PASS_WITH_LIMITATIONS`；其 operational report 明确未评估正确性。后续 Prompt 10 评估报告为 `COMPLETE`，扩展建议为 `INCONCLUSIVE`，未通过 `gold_validity` 与 `mixed_discrimination` 门槛；不能把 operational report 的通过状态解读为质量达标。

## 指标定义

3 PR 的评估身份是 `scrapy-3pr-prompt10-v1`，评估器版本 `prompt10-evaluator-v1`，指标定义版本 `prompt10-metrics-v1`。评估计划使用文件和符号两个层级、排名截断 1/3/5；原始指标来自 `batch/evaluator.py` 的 `score_ranked`，汇总来自 `_metric_summary`。20 PR 只有 Detect 运行证据，没有该批的 gold 评估或同等指标汇总。

- 对预测集合与 gold 集合，`tp` 为交集数，`fp` 为仅预测数，`fn` 为仅 gold 数。`precision = tp / |predicted|`，`recall = tp / |gold|`，`f1 = 2PR/(P+R)`；空分母时取 0。
- `exact_match` 表示集合完全相同；`any_hit` 表示至少命中一个；`all_hit` 表示 gold 是预测集合的子集。`hit_at_k` 表示前 k 项至少一项命中，`recall_at_k` 为前 k 项命中数除以 gold 数；`mrr` 是首个命中名次的倒数，无命中为 0。
- 汇总按有效目标计算宏平均；微平均先汇总 `tp/fp/fn` 再计算 precision、recall、F1。无效数与缺失数另列，不应当当作零分目标。评估计划的任务权重为 `equal-task-macro`，并按 `TEST_ONLY_PR`、`MIXED_CODE_AND_TEST_PR`、`ALL` 分类。
- Update 的 `sealed-detect` 与 `self-directed` 成对比较要求 task、分类、方法、base SHA、资源配置、gold seal、指标版本和有效性一致。`self-directed` 与 Detect 的重叠是事后非因果观察；`sealed-detect` 的 handoff 才是因果比较。3 PR 评估记录 9 Detect、18 Update、18 behavior、2 invalid 和 9 eligible pairs。

以上仅记录指标语义、版本及产物身份，不在基线中复制 gold 值、预测内容或评价矩阵内容。

## 复核方法

从两个 `batch/pilot/*.json` 依配置顺序展开：每个 task/method 生成一个 `(task_id, method, detect, null, detect.run_id)`，每个 `updates[]` 生成一个 `(task_id, method, update, update.mode, update.run_id)`。将五元组与对应 ledger 的 `target.update_mode`、seal 的 task/method/run_id/mode 逐项对照；对 Detect seal 没有 mode 字段时按 `null` 处理。每个封存目标应有封存事件和匹配 seal。再核对 3 PR Detect barrier 的 9 条记录及 final audit 的 27 个目标。按路径重算 SHA-256 并以稳定顺序、UTF-8、两空格缩进生成 JSON，即可重复得到 `baseline.json`；不得运行模型或 Docker。
