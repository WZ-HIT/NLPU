# 阶段 A 完成报告：补生成、源码抽检和新版 TI

版本：v1，2026-11-09。状态：TI-18、TI-19 已验收完成，新版材料已在本地导出。范围仍是原 30 PR 涉及的 22 个公开 base；未启动新的定位实验。

## 最终交付

新版材料位于 [publication-v1](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/publication-v1)，每个 base 有独立目录、读取器和来源清单。原 P2 材料、旧缓存及本轮原始生成结果均保留。

| 项目 | 原 P2 材料 | 新版 TI |
| --- | ---: | ---: |
| base 数 | 22 | 22 |
| 版本化测试记录 | 53,249 | 53,249 |
| 有语义意图的记录 | 46,975 | **53,145** |
| 静态回退记录 | 6,274 | **104** |
| 语义意图覆盖率 | 88.22% | **99.80%** |

这里的覆盖率表示记录是否有可用语义字段，不是语义正确率或定位召回率。发布状态是 `PARTIAL_COVERAGE`：104 条仍然只有静态事实和源码，不能称为全量语义增强。

## 补生成的实际结果

772 个输入包全部尝试结束：762 个通过结构、身份和证据引用校验，3 个失败回退，7 个请求结果及用量未返回，没有待派发请求。

生成阶段提供了 6,218 条新语义记录。源码抽检后，其中 8 条因整包隔离被撤下，最终保留 **6,210 条本轮新语义**。另外撤下 40 条旧复用语义，因此全库有语义记录的净增加量是 **6,170 条**。

| 新版仍缺少语义的来源 | 记录数 |
| --- | ---: |
| 生成失败或结果未决 | 56 |
| 本轮新生成结果因质量问题隔离 | 8 |
| 旧复用结果因质量问题隔离 | 40 |
| 合计 | **104** |

逐条身份和原因见 [未解决清单](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/closeout/unresolved.json)，逐 base 统计见 [发布汇总](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/publication-v1/summary.json)。这些记录没有被静默删除，仍可搜索静态事实并回查源码。

## 48 条样本的源码审查

使用生成前固定的、不依赖隐藏标签的抽样规则：每个 base 的新生成与旧复用记录，以及长测试、多个场景、继承、mock、条件和剩余回退。共 48 条：25 条旧复用、22 条新生成、1 条无语义记录。

逐条源码核对结果为：**45 条接受、2 条整包隔离、1 条确认无语义**。审查由 Codex root agent 完成，没有新增批量生成或模型评审请求。没有要求用户人工填写审查表，也没有把所有记录默认设为接受。

| 不合格样本 | 源码与描述的差异 | 处理 |
| --- | --- | --- |
| `test_http_headers.py::test_encode_utf8`，旧复用 | 源码的键是 `key`，值是 `£`；意图的条件把 `£` 写成了键 | 隔离同一生成键的 40 条版本化记录 |
| `test_feedexport_batch.py::TestBatchDeliveries.test_export_items`，新生成 | 意图把缺失字段为空字符串概括为跨格式预期；公开源码中 JSON Lines 和 pickle 会先过滤空值，CSV 才保留空字段 | 隔离同一生成键的 8 条版本化记录 |

第二个问题也暴露了输入材料的局限：生成时只展开到抽象的格式 helper，实际覆盖方法未进入该输入包。意图虽保留了这一未知项，仍给出了过宽的确定预期。本阶段隔离问题，不重新生成或修改描述。

全部结论、源码锚点和文件哈希见 [逐条审查报告](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/quality/report.md) 与 [review.json](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/quality/review.json)。冻结样本为 [sample.json](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/quality/sample.json)。

这是一轮固定规则的抽检，并非全部 53,249 条逐项审查；不能把 45 条接受的比例外推成全库正确率。

## 导出与验收

新版格式为 `compact-intention-v5`，更新短卡片、完整语义及检索索引，关闭语义文件主题。测试身份、源码位置、静态事实、上下文、关系边和维护事实数据库均保留。

验收已完成：

- 旧 2,593 个成功输入包重新通过结构和逐测试证据检查；新结果逐包核对账本、原回复、生成配置和哈希。
- 22 个 base 的全部 53,249 个测试身份和静态字段与旧材料一致。
- 重核 16,962 个冻结来源文件；全部发布文件清单及哈希通过检查。
- 逐项核对 4,109,805 个检索字段的原文引用，确认维护事实没有丢失，静态回退没有残留隔离的语义字段。
- 574 次读取检查覆盖独立 CLI 检索、卡片、场景、上下文、关系、维护事实、命中回查和分页。
- 48 条样本的 796 行测试源码通过分页读取完整还原；游标顺序、无重复和失效检查通过，输出分别受 6,000／12,000 字节限制。
- 原恢复、生成路由、续跑和发布相关的 28 项离线测试通过。

证据：[生成收尾核对](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/closeout/summary.json)、[全量发布检查](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/release-verification.json)、[读取器检查](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/reader-verification.json)。复核入口为 [stage_a_acceptance.py](test_intention/stage_a_acceptance.py)。

## 请求与用量

本轮有效计划实际启动 CLI **780 次**，另保留一次早期模型不受账户支持的失败启动，共 **781 次**，低于含早期启动在内的 1,544 次边界。CLI 内部可能有网络重试，不能把启动数写成准确的 provider HTTP 请求数。

| 已知 CLI 用量 | token |
| --- | ---: |
| 输入 | 9,435,841 |
| 输出 | 1,858,372 |
| 合计 | 11,294,213 |
| 其中缓存输入，已包含在输入中 | 1,545,984 |
| 其中推理输出，已包含在输出中 | 375,586 |

有效计划有 8 次启动缺失用量：7 次结果未决，另 1 次失败回复没有完整 usage。早期不支持模型的失败启动也缺失用量，单独保留，不能将缺失填零。

生成使用 ChatGPT Plus 订阅，新增直接 API 调用和额外额度购买均为 0。上述 token 不换算成 Plus 订阅账单。本次抽检、导出和验收没有新增生成请求。

## 后续比较的边界

新版混合 46,935 条旧复用语义和 6,210 条本轮新语义，生成模型、提示和分包均与旧材料不同。后续可以比较材料可用性的整体影响，不能将差值称为单独补齐覆盖的因果收益。

实际覆盖、隔离和材料哈希已写入 [TI-14 材料修订](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/comparison-material-amendment-20261109-v1.json)。修订仍关闭实验执行；B/C 材料隔离、共同运行环境、正式运行边界等后续任务未因 A 完成而自动完成。

本次没有读取隐藏标签来选择样本或修改意图，没有重跑原始直接定位基线，没有启动新的 SDD 定位请求，也没有修改正式 context。
