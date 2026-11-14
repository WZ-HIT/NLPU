# 实验 token 记录与 sdd-results 展示

SDD Results v1.5.0 同时展示 token 用量及文件／testcase 双粒度指标。
不改变现有 PR 分组、round 身份、模型提示或评分公式，不自动启动实验。

## 使用

```bash
cd ~/NLPU/sdd-bench/scrapy-sdd
python3 bin/check-testcase
sdd-results
```

若服务已经启动，Ctrl+C 后重新执行 `sdd-results`，浏览器刷新。无需修改实验配置。
正在运行的旧 Agent 进程无需为此停止；其完成后保存的日志也可被新页面读取。

- 首页实验卡片：含重试的已记录 token 小计及用量覆盖次数。
- 批次总览：输入、缓存输入、输出、总量，三种方法汇总，以及每次尝试明细。
- 单 PR 页面：只统计该 PR 的方法与尝试，不混入同批其他 PR。
- 方法明细：显示最新已封存尝试的 token 数；此前失败／重试成本在总览的尝试表中保留。
- 旧式实验：读取每个方法 `phases/*.jsonl` 的阶段日志；没有日志或 usage 就显示未记录。

## 记录文件与来源

新启动的正式 Detect／Update 调用在保存 Agent stdout 后、检查退出码前，写入一次
`token-usage.json`。因此非零退出也保留已经报告的用量。

- Detect：`.../detect/executions/<run-id>/attempt-N/token-usage.json`
- Update：`.../update/executions/<run-id>/attempt-N/mode-<mode>/artifacts/token-usage.json`

契约为 `agent-token-usage-v1`，schema 是
`schemas/agent-token-usage-v1.schema.json`。
字段包括 input/cached_input/cache_write_input/output/reasoning_output/total token、
有效完成轮数、无效事件数、状态、进程退出码，以及源 `agent.jsonl` 的 SHA-256 和字节数。
`usage_sha256` 绑定除自身外的规范化 JSON。任务、方法、阶段、模式、run_id 和 attempt 由
原目标身份、执行目录与 ledger 关联；新 sidecar 随原执行 bundle 一起封存。
记录中没有 prompt、回复正文、凭据或 gold 内容。

历史封存产物不补写 sidecar。页面从其原日志只读提取数字与来源哈希，不修改 ledger 或 seal。
页面以当前日志为来源，不盲信可能过期的 sidecar。单日志解析按路径、内容哈希、mtime 与大小缓存，
日志更新后重新读取；正在变化的读取结果标记部分记录。

## 计数口径

累加 JSONL 中每个 `turn.completed.usage`：

```text
total_tokens = input_tokens + output_tokens
```

- cached_input_tokens 已包含在 input_tokens 中，不再次相加。
- reasoning_output_tokens 已包含在 output_tokens 中，不再次相加。
- cache_write_input_tokens 仅保留供应方提供的数值，不额外加入总量。
- 不将累计 `token_count`／会话快照再加一次。
- 可选字段缺失显示未记录，不估算为零；任一已记录尝试缺少该可选字段时，分组对应字段也显示未记录。
- 总量是供应方报告的 token 数，不是美元费用，也不是去除缓存后的计费用量。

主合计包括当前配置目标在有效 ledger 中出现的全部正式尝试，保留失败尝试。
重复状态事件、SKIPPED_RESUME、probe 和未被 ledger 引用的孤立 attempt 文件不重复计费。
Detect／Update 及两种 Update 模式按原五元目标键分别关联，不能跨模式或跨轮次串用日志。

| 状态 | 含义 |
| --- | --- |
| RECORDED | 必需的输入／输出用量完整，可能有可选字段未提供 |
| PARTIAL | 有已知数值，但日志中断、截断或部分尝试缺少用量；只展示已知小计 |
| NOT_RECORDED | 没有可信 usage，不当作零 |
| UNREADABLE | 源文件无法读取，不当作零 |

供应方在失败前没有返回 usage 时，无法仅凭回复文本还原准确 token 数。
明确返回 input=0、output=0 才显示真实零；没有记录不等于没有消耗。

## 文件级与 testcase 指标

三套既定指标继续使用 `detect-metrics-v3`，公式不变：历史文件级、同范围文件级、testcase 级。
页面同时显示 P/R/F1、预测／gold／命中数、宏平均／微平均、计分覆盖和失败／无效预测数。
单 PR 的统计范围限制到该 PR，明细默认展开。

用量无需先评估即可从日志显示。定位指标必须先在宿主机生成：

```bash
python3 bin/sdd-experiment evaluate "$CONFIG" --round "$ROUND" --kind testcase
```

或对实际批次 ID：

```bash
python3 bin/sdd-detect-metrics check --batch <batch-or-round-id> --testcase
```

未生成报告时页面明确显示命令，不显示伪造的零分。
报告损坏或版本不支持会显示不可读取；ledger、目标状态或 attempt 已变化时，提示评分过期，
不将旧分数当成当前分数。页面不自动读取 gold 计算分数。
本次新增区块只展示计数和分数，不导出宿主机 gold 方法身份或源码。

## 验证范围

一键验收包含 parser、缓存／推理子项去重、累计快照忽略、缺失与真实零、截断、失败记录、
schema／来源哈希、全部重试统计、probe／resume 去重、Update 模式隔离、旧阶段日志、
只读页面、双粒度展示、缺失／损坏／过期评分及假 Agent 封存流程。
当前 4 组、78 项检查通过；未运行真实模型或 Docker。

另对历史 `scrapy-3pr-detect-v2` 的 9 个目标做只读检查：18 次正式尝试中 9 次有 usage、9 次缺失，
页面按 PARTIAL 展示已知小计；28 个日志、ledger、seal 和 detection manifest 文件的哈希前后相同。
这项检查仅覆盖该历史批次，不表示已核查全部 98 PR 的 token 日志。
