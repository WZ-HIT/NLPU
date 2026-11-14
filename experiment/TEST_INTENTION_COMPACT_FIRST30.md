# 精简意图：原首批30PR重跑

用户已明确要求用当前精简表示重新运行前30个PR。本轮为完整的新定位实验，不复用首3PR的模型预测，不重跑原基线模型。

当前状态：冻结轮次 `round-fc2b0bbcfbfef43648460ff7` 的90项Detect已全部终结，比较评分完成，配对输入与运行配置检查均通过。64项成功封存，26项失败；其中23项预算耗尽、2项服务端余额不足、1项结果处理报错。失败按零分纳入评价，没有自动重试。详见[结果报告](TEST_INTENTION_COMPACT_FIRST30_RESULTS.md)。

## 固定条件

- 顺序沿用 `scrapy-30pr-testcase-v1.json` 的原30个PR，OpenSpec／Spec Kit／cc-sdd各30项，只有Detect阶段。
- PR title/body、base、测试身份和宿主机评价协议沿用原批次。新预测全部终结前不进入宿主机评分阶段。
- 使用既有 `compact-v2` 的22份表示，不重新生成意图。与首3PR重叠的base，其材料清单逐字节相同。
- deepseek-flash/high，rollout预算100,000 token，单项超时2700秒。实际三份runtime配置及launcher哈希与首3PR一致，并在每次Detect前和结束后检查。
- 同方法PR串行，三种方法并行；先完成全部容器／隔离准备检查。失败保留为零分，不自动重复付费尝试。

## 独立产物

```text
/data2/wangzuohit/NLPU-experiments/test-intention/compact-first30-v1/
```

`scope.json`、`method-match.json`、`runtime-lock.json` 固定范围、与小批验证的一致性及运行配置。`execution-root/` 保存新工作区。`prepared-reference.json` 保存冻结轮次入口。`execution-status.json` 及父目录 `compact-first30-workflow.log` 保存执行状态。

完成90项后，`terminal-targets.json` 绑定完整终结状态和ledger哈希；随后才生成 `host-comparison/` 与 [结果报告](TEST_INTENTION_COMPACT_FIRST30_RESULTS.md)。全部90项终结后才生成结果报告。评价目录含宿主机标签资料，不提供给Agent。

## 比较方式

同一90项比较三组：

| 组 | 来源 | 新模型调用 |
| --- | --- | --- |
| 原方案一 | `round-65f66ff1426e4c7d1f8da662` 的已保存结果 | 无 |
| 第一版完整证据包 | `round-bd7ad4062f5b682721540c3a` 的已保存结果 | 无 |
| 当前精简意图 | 本轮独立prepare和90项新Detect | 90个正式目标 |

先核对完整配对身份、公共task快照、测试清单、标签和可计分集合。独立从每项TP/FP/FN复核P/R/F1，再检查macro和micro汇总。报告失败数、预算耗尽数、无正例任务误报、材料相关工具输出字符及逐PR差值。

字符统计不等同于实际token；历史失败任务的provider用量有缺失，不能把缺失算作零。历史运行时配置字节未独立固定，不能把全部分数变化只归因于表示。

## 执行命令

```bash
python3 -m experiment.test_intention.compact_first30 setup
python3 -m experiment.test_intention.compact_first30 prepare
python3 -m experiment.test_intention.compact_first30 run
python3 -m experiment.test_intention.compact_first30 compare
```

已完成的setup不重复执行；中断后核对状态，已封存或失败目标不自动重跑。该入口仅改变新轮次，不覆盖原30PR或首3PR的输入及封存证据。
