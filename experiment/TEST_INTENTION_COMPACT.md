# 精简测试意图与按需证据

本轮改版已获用户确认。目标是在定位阶段减少重复材料的读取，同时保留测试行为和可追溯证据。继续在 `experiment/test-intention` 分支工作，历史30PR轮次和原始表示均保留。

## 已实施的组织方式

原始 JSON 仍是宿主机的正式原始记录。本轮复用这些记录导出阅读视图，没有重新调用模型生成描述。

| 层次 | 内容 | 阅读方式 |
| --- | --- | --- |
| 总目录 | 测试文件、主题样例、条目数和入口 | 先分页列文件；不再集中重复列出全部方法 |
| 测试意图 | ID、源码位置、行为目标、输入/mock、条件与预期对应、依赖候选、未知状态、证据引用 | 默认摘要按原测试文件组织；支持跨全部语义字段搜索 |
| 按需证据 | 完整已有语义描述、静态事实、共享上下文位置、局部依赖关系 | 按测试 ID 查看对应视图，分页返回 |
| 原始证据包 | 原测试源码、展开依赖源码及完整旧记录 | 留在宿主机审计；Agent需要源码时读取原仓库的对应位置 |

共享上下文仅保存一份位置和校验码引用，完全相同的关系边去重。详细视图使用标准库生成的只读二进制索引保存 JSON 字段，便于按 ID 查询；它是派生数据，不替代原始 JSON。Agent 不需要读取或解码整个索引。

当前缓存没有独立生成“提示”字段，也没有逐项证明某条静态依赖是关键依赖。摘要保留这一事实：提示标记未单独生成；依赖标为有依据的静态候选。没有添加针对当前 PR 的更新建议，也没有把未知改成确定行为。

## 阅读入口与上限

三种 SDD 的新工作区公共入口仍是 `/workspace/test-intentions/README.md`。常用命令：

```bash
python3 test-intentions/read.py files
python3 test-intentions/read.py search --query keyword
python3 test-intentions/read.py show 'tests/example.py::Class.test_method'
python3 test-intentions/read.py scenarios 'TEST_ID'
python3 test-intentions/read.py detail 'TEST_ID' --field environment_mock
python3 test-intentions/read.py facts 'TEST_ID' --field assertions
python3 test-intentions/read.py contexts 'TEST_ID'
python3 test-intentions/read.py relations 'TEST_ID'
python3 test-intentions/read.py source 'TEST_ID'
```

搜索始终覆盖全部测试及完整语义字段，包括摘要预览中未列出的内容；可重复 `--query` 表示任一关键词匹配。目录及关系只帮助导航，不限制候选集合。

每次默认最多返回6,000字节、8条记录；输出最高12,000字节。返回 `next_offset` 时可以继续分页。单条信息过长时，明确输出编号的 JSON 文本片段，拼接后可恢复完整记录；不会静默截断句子或丢掉场景。默认摘要使用 `more/read` 明示省略了多少项及展开方式。

默认 `rg` 排除完整清单、全图提示文件、读取器源码和二进制证据索引。定位说明也要求通过分页入口读取。原生 shell 仍可绕过这些约定，例如显式递归扫描全部摘要；因此它控制推荐读取路径，不能保证任何Agent都不耗尽预算。

## 离线核查结果

产物位于 `/data2/wangzuohit/NLPU-experiments/test-intention/compact-v2/`。

- 22 个 base、53,249 条测试身份全部保留；完整语义、完整场景和回退状态逐条比对通过。
- 原发布包共1,221,865,809字节，新包487,185,461字节，减少60.13%。这包含按需证据索引，不是全部默认输入。
- 总索引合计缩小94.41%。新增按文件组织的摘要可以搜索；不再依靠一次读取全仓方法目录。
- 3项新增合成检查覆盖多场景不丢失、未知保留、上下文/边去重、证据篡改拒绝、只读查询、源码引用安全、分页重组和输出上限。
- 连同原意图及round/testcase相关检查，共38项通过；随后新增的3项控制器检查也通过，覆盖9项真实Ledger调度、调用前启动记录/配置核验、失败记录保留、先筛9项再汇总、配置变更拒绝。独立检查另外验证了汉字、emoji、控制字符分页重组和默认 `rg` 排除。
- 新增模型生成调用为0。
- 单条默认意图卡片在各base的中位大小为982～1,343字节，旧完整记录为17,567～20,839字节。这里仅比较卡片内容，不含分页包装，也不能直接换算成token。
- 独立全量复核保留71,727个场景、280,283项未知记录和678,130个上下文引用；实际运行镜像内的读取器调用也通过。

程序入口是 `experiment/test_intention/compact.py`、`reader.py`，验证入口是 `tests/test_compact_intention.py`。离线报告为 `export-summary.json`、`content-verification.json`。

## 已授权的9项运行验证

只运行原首3个PR：8064、8067、8073，各运行 OpenSpec、Spec Kit、cc-sdd，共9项。使用独立产物目录 `/data2/wangzuohit/NLPU-experiments/test-intention/compact-first3-v1/`，保持旧轮次不变。

模型固定为deepseek-flash/high，定位rollout预算100,000 token，单项超时2700秒。将实际总配置、模型配置、模型目录和启动代码的哈希写入 `runtime-lock.json`；准备前、每次正式定位前和运行结束后都核验。

```bash
python3 -m experiment.test_intention.compact_pilot setup
python3 -m experiment.test_intention.compact_pilot prepare
python3 -m experiment.test_intention.compact_pilot run
python3 -m experiment.test_intention.compact_pilot compare
```

全部9项终结后才在宿主机评分。原基线和旧证据包组都先取相同9项再重新汇总，保留失败零分；不拿原30PR均值与新3PR均值直接比较。评价资料不进入新Agent输入。

同时报告完成率、预算耗尽次数、材料读取输出量和方法级P/R/F1。读取字符或字节不是实际token；失败任务的provider token记录可能不完整，不能以缺失值冒充零。

这是运行方式的小批验证，不代表完整30PR效果。是否扩大到30PR由用户决定，不自动扩大实验。


当前验证轮次：`round-3ad197495968e9e84ad7d508`。9项Detect及配对评分均已完成，9项全部成功封存，预算耗尽0次。完整结果见 [首3PR结果](TEST_INTENTION_COMPACT_RESULTS.md)。


## 首3PR结果摘要

旧证据包版本在相同9项中4次因预算耗尽失败，本轮为0次。涉及意图材料命令的平均输出从130,873字符降至35,483字符，减少72.89%；全部工具输出平均减少39.32%。这些是日志字符统计，不是精确token或费用对照。

每种SDD有2个正例PR参与macro均值，精简版recall均为100%，恢复至原基线水平。OpenSpec/Spec Kit的macro precision和F1为100%；cc-sdd分别为75%与83.33%，有1项额外预测。另1个无正例PR中，精简版共报告6个候选，原基线2个、旧证据包1个；因此不能以完成率和recall恢复宣称全面准确度提升。

内容分层与分页已通过本次小批运行检查。完整30PR未重跑，原基线未重新调用模型。历史运行时模型配置字节仍未独立固定，比较保留这一局限。


## 已授权的完整30PR重跑

用户随后明确要求用当前精简表示重跑原前30个PR。独立新轮次的范围、固定参数和执行状态见 [完整30PR重跑](TEST_INTENTION_COMPACT_FIRST30.md)。首3PR结果保持历史记录。
